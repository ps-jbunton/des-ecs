"""
Core running engine for a discrete-event simulation married to an entity-component system.
"""

import abc
import dataclasses
import sqlite3
from typing import Iterable, Iterator, TypeVar

import polars as pl
import simpy

import util


def id_generator() -> Iterator[int]:
    """
    Generator that just increments the entity count by one.
    """
    id_counter = 0
    while True:
        yield id_counter
        id_counter += 1


@dataclasses.dataclass
class Component:
    """
    Base for all components.
    """


C = TypeVar("C", bound=Component)


class ComponentDict:
    """
    Convenience wrapper around a dictionary that can be queried for component types.  Mostly useful
    for type-hinting purposes.
    """

    def __init__(self, data: dict[type[C], C] | None = None) -> None:
        self.data = data or {}

    def get(self, c_type: type[C]) -> C:
        """
        Gets a component of the given type, if one exists, raises `KeyError` otherwise.
        """
        return self.data[c_type]

    def add(self, component: C) -> None:
        """
        Adds a new component.  If one already exists, it is overwritten.
        """
        self.data[type(component)] = component

    def components(self) -> Iterable[type[Component]]:
        """
        Return all component types currently in the dictionary.
        """
        return self.data.keys()

    def pop(self, component_type: type[C]) -> C:
        """
        Pops the given component type.
        """
        return self.data.pop(component_type)

    def items(self) -> Iterator[tuple[type[Component], Component]]:
        """
        Iterates over entries in the dict.
        """
        for key, value in self.data.items():
            yield key, value


@dataclasses.dataclass
class ComponentManager:
    """
    Basic Component-System.  Manages two separate dictionaries for fast querying.

    entity_to_components:
        Maps from an integer ID to a dict from `ComponentType` to `Component`s that the entity
        contains.
    component_type_to_entities:
        Maps from a `ComponentType` to a set of entity IDs that have this component type.
    """

    entity_to_components: dict[int, ComponentDict] = dataclasses.field(
        default_factory=lambda: {}
    )
    type_to_entities: dict[type[Component], set[int]] = dataclasses.field(
        default_factory=lambda: {}
    )

    # A generator for entity IDs.
    _entity_id_generator: Iterator[int] = id_generator()

    def new_entity(self, components: Iterable[Component] | None) -> int:
        """
        Create a new entity with the given `Component`s.
        """
        entity_id = next(self._entity_id_generator)
        self.entity_to_components[entity_id] = ComponentDict()
        if components is not None:
            for component in components:
                c_type = type(component)
                self.entity_to_components[entity_id].add(component)
                if c_type not in self.type_to_entities:
                    self.type_to_entities[c_type] = {entity_id}
                else:
                    self.type_to_entities[c_type].add(entity_id)
        return entity_id

    def remove_entity(self, entity_id: int) -> None:
        """
        Remove an entity from the ECS.
        """
        # Remove entity ID from entity dictionary.
        component_dict = self.entity_to_components.pop(entity_id)
        for c_type in component_dict.components():
            self.type_to_entities[c_type].remove(entity_id)

    def get_entity(self, entity_id: int) -> ComponentDict:
        """
        Get a dict mapping `ComponentType` to `Component` for all `Component` instances assigned to
        the given entity.
        """
        return self.entity_to_components[entity_id]

    def get_entities(self) -> Iterator[tuple[int, ComponentDict]]:
        """
        An iterator over all entities in the ECS.
        """
        for entity, comp_dict in self.entity_to_components.items():
            yield entity, comp_dict

    def add_components(self, entity_id: int, components: Iterable[Component]) -> None:
        """
        Add the given components to the entity with the given ID.  If one of the given type already
        exists, it is replaced.
        """
        for component in components:
            c_type = type(component)
            self.entity_to_components[entity_id].add(component)
            if c_type not in self.type_to_entities:
                self.type_to_entities[c_type] = {entity_id}
            else:
                self.type_to_entities[c_type].add(entity_id)

    def remove_components(
        self, entity_id: int, component_types: Iterable[type[Component]]
    ) -> None:
        """
        Removes components of given types from the entity with the provided ID.  If the entity does
        not have a component of the given type, raises a `KeyError`.
        """
        for c_type in component_types:
            self.type_to_entities[c_type].remove(entity_id)
            self.entity_to_components[entity_id].pop(c_type)

    def get_components(
        self, component_types: Iterable[type[Component]]
    ) -> Iterator[tuple[int, ComponentDict]]:
        """
        Returns an iterator over pairs of entity, dicts of components for entities that match the
        given component types.
        """
        try:
            for entity in set.intersection(
                *[self.type_to_entities[c_type] for c_type in component_types]
            ):
                yield entity, self.get_entity(entity)
        except KeyError:
            # No entities registered with one or more component types.
            pass


# Here, we tie the event-triggered nature of `simpy` to the `System` class.
class System(abc.ABC):  # pylint: disable=too-few-public-methods
    """
    A base system has an `update` method that operates on the entire ECS.
    """

    @abc.abstractmethod
    def update(
        self, env: simpy.Environment, component_manager: ComponentManager
    ) -> simpy.Event | None:
        """
        System update function.  It iterates through relevant portions of the ECS, performing any
        operations necessary on the contained components.  It returns a `simpy.Event` that will
        "trigger" to alert the main simulation loop to perform another iteration.
        """


@dataclasses.dataclass
class Recorder:
    """
    Database connection for the simulation.
    """

    db: sqlite3.Connection
    db_path: str
    db_name: str
    is_open: bool

    @classmethod
    def make(cls, db_path: str, db_name: str = "sim_records"):
        """
        Holds records within a database using SQlite3.
        """
        try:
            db = sqlite3.connect(db_path)
            db.execute(f"DROP TABLE IF EXISTS {db_name}")
            db.execute(
                f"CREATE TABLE {db_name} "
                f"(timestamp FLOAT, "
                f"entity INT, "
                f"component TEXT, "
                f"attribute TEXT, "
                f"value)"
            )
            return cls(db=db, db_path=db_path, db_name=db_name, is_open=True)
        except Exception as e:
            raise ConnectionError("Could not connect to records database!") from e

    def close_db(self):
        """
        Closes the database connection.
        """
        self.db.commit()
        self.db.close()
        self.is_open = False

    def record_component(self, time: float, entity: int, component: Component):
        """
        Add information to the running simulation records.

        Args:
            state:
                Dictionary of values to save in the records.
            prefix:
                The string prefix (key) to put this entry in within the simulation records.  If none
                is given, the value is recorded at the top 'SIM' prefix.
        """
        for attribute, value in util.dataclass_to_dict(component).items():
            self.db.execute(
                f"INSERT INTO {self.db_name} (timestamp, entity, component, attribute, value) "
                f"VALUES "
                f"(?, ?, ?, ?, ?)",
                (
                    time,
                    entity,
                    str(type(component).__name__),
                    attribute,
                    value,
                ),
            )

    def to_polar_dataframe(self):
        """
        Converts the current database to a polars dataframe.
        """
        if not self.is_open:
            db = sqlite3.connect(self.db_path)
            df = pl.read_database(query=f"SELECT * FROM {self.db_name}", connection=db)
            db.close()
            return df
        return pl.read_database(
            query=f"SELECT * FROM {self.db_name}", connection=self.db
        )


@dataclasses.dataclass
class World:
    """
    Holds the `ComponentManager` and the `System`s and iterates through them at each update loop.
    """

    env: simpy.Environment
    systems: list[System]
    component_manager: ComponentManager
    recorder: Recorder

    @classmethod
    def make(
        cls,
        env: simpy.Environment | None = None,
        systems: list[System] | None = None,
        component_manager: ComponentManager | None = None,
    ):
        """
        Makes a new instance.
        """
        return cls(
            env=env or simpy.Environment(),
            systems=systems or [],
            component_manager=component_manager or ComponentManager(),
            recorder=Recorder.make(
                db_path="./data/generated/sim_db.sqlite", db_name="sim_records"
            ),
        )

    def run(self, until: float):
        """
        Runs the simulation for the given amount of time.
        """
        self.env.process(self.loop())
        self.env.run(until=until)
        self.recorder.close_db()

    def loop(self):
        """
        Main simulation loop.  Systems are iterated any time an event is triggered.
        """
        while True:
            shared_events = []

            for system in self.systems:
                event = system.update(self.env, self.component_manager)
                if event:
                    shared_events.append(event)

            for entity, components in self.component_manager.get_entities():
                for _, component in components.items():
                    self.recorder.record_component(
                        time=self.env.now, entity=entity, component=component
                    )
            if shared_events:
                yield self.env.any_of(shared_events)
            else:
                break
