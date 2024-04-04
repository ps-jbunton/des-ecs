"""
Actual instantiations of various bases in the DES-ECS core.
"""

import dataclasses
import enum
import random

import simpy

from des_ecs import Component, ComponentDict, ComponentManager, System, World


@dataclasses.dataclass(kw_only=True)
class Position(Component):
    """
    A position component for a vehicle.
    """

    x: float = 0
    y: float = 0


class CommandState(enum.Enum):
    """
    The state of a commandable entity.
    """

    IDLING = enum.auto()
    EXECUTING = enum.auto()


@dataclasses.dataclass
class Commandable(Component):
    """
    Component that indicates an entity may receive commands.
    """

    state: CommandState = CommandState.IDLING


@dataclasses.dataclass
class Destination(Component):
    """
    A destination for an entity.
    """

    x: float
    y: float


@dataclasses.dataclass
class MoveCommand:
    """
    Commands a vehicle to change its position.
    """

    delta_x: float = 0
    delta_y: float = 0


@dataclasses.dataclass
class IncomingCommand(Component):
    """
    An incoming `MoveCommand` for an entity.
    """

    command: MoveCommand


@dataclasses.dataclass
class ExecutingCommand(Component):
    """
    The `MoveCommand` that is currently being executed.
    """

    command: MoveCommand


class MoveCommandSystem(System):  # pylint: disable=too-few-public-methods
    """
    Command issuing system.  For entities that are `Commandable` and have `RailPosition`s.
    """

    required_components = (Commandable, Position, Destination)

    def update(
        self, env: simpy.Environment, component_manager: ComponentManager
    ) -> None:
        # Iterate over all commandable entities.
        for entity, components in component_manager.get_components(
            component_types=self.required_components
        ):
            if components.get(Commandable).state == CommandState.IDLING:
                x, y = (
                    components.get(Position).x,
                    components.get(Position).y,
                )
                dest_x, dest_y = (
                    components.get(Destination).x,
                    components.get(Destination).y,
                )
                delta_x, delta_y = (dest_x - x) / 2, (dest_y - y) / 2
                if max(abs(delta_x), abs(delta_y)) > 1e-2:
                    component_manager.add_components(
                        entity,
                        [
                            IncomingCommand(
                                MoveCommand(delta_x=delta_x, delta_y=delta_y)
                            )
                        ],
                    )


class CommandExecutionSystem(System):
    """
    Command execution system.  For `Commandable` entities with an `IncomingCommand`.
    """

    required_components = (Commandable, IncomingCommand, Position)

    def update(
        self, env: simpy.Environment, component_manager: ComponentManager
    ) -> simpy.Event | None:
        """
        Transitions all commandable entities with an incoming command
        """
        shared_events = []
        for entity, components in component_manager.get_components(
            self.required_components
        ):
            # Copy the command rom `Incoming` to `Executing`
            self.entity_startup(entity, components, component_manager)
            # Create a timeout event that will trigger when the command is about to finish.
            completion_event = env.timeout(delay=random.random())

            shared_events.append(
                env.process(
                    self.entity_cleanup(
                        completion_event, entity, components, component_manager
                    )
                )
            )
        if shared_events:
            return env.any_of(shared_events)
        return None

    def entity_startup(
        self,
        entity: int,
        components: ComponentDict,
        component_manager: ComponentManager,
    ):
        """
        Commands for initial processing of the entity's components.
        """
        component_manager.add_components(
            entity, [ExecutingCommand(command=components.get(IncomingCommand).command)]
        )
        component_manager.remove_components(entity, [IncomingCommand])
        components.get(Commandable).state = CommandState.EXECUTING

    def entity_cleanup(
        self,
        triggered_event: simpy.Event,
        entity: int,
        components: ComponentDict,
        component_manager: ComponentManager,
    ):
        """
        Commands for changing entity's components upon command completion.
        """
        yield triggered_event
        self.update_position(
            position_component=components.get(Position),
            command=components.get(ExecutingCommand).command,
        )
        components.get(Commandable).state = CommandState.IDLING
        component_manager.remove_components(entity, [ExecutingCommand])

    def update_position(self, position_component: Position, command: MoveCommand):
        """
        Updates the position component.
        """
        position_component.x += command.delta_x
        position_component.y += command.delta_y


def run_quick_sim(until=100):
    """
    Creates instantiation of the above small example.
    """
    # Instantiation of the examples.
    component_manager = ComponentManager()

    for _ in range(1000):
        component_manager.new_entity(
            components=(Position(), Commandable(), Destination(x=10, y=10))
        )

    move_system = MoveCommandSystem()
    exec_system = CommandExecutionSystem()

    world = World.make(
        systems=[move_system, exec_system], component_manager=component_manager
    )

    world.run(until)
    world.recorder.to_polar_dataframe().to_pandas().to_parquet(
        "./data/generated/sim_db.parquet"
    )


if __name__ == "__main__":
    run_quick_sim()
