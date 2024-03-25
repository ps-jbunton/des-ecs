# DES-ECS

An attempt at marrying two ideologies that don't work well together: an entity-component system and a discrete-event simulation.

## ECS
Entity component systems (ECS) are often built under the premise that each system will be called every "game loop", once per game loop, in a deterministic order.  The benefit they bring to a simulation (and, more typically, games) is a performance-oriented architecture that promotes data-oriented design.

As a quick intro, in an ECS, all of the data that comprises an `Entity` in the simulation is encapsulated inside various `Component`s.  A `Entity` is just a unique identifying ID (an `int`) that is associated with that `Component`.  The only objects that are permitted to manipulate the `Component`s are `System`s, which may request access to all entities that contain a specified subset of `Component`s and manipulate them.

Typically, when using an ECS, one would have a centralized "sim loop" that looks like:

```
while t < MAX_TIME:
    t += dt
    for system in systems:
        system.update(ecs)
```
where the systems are sorted in priority, and inside their `update` functions, they query the ECS object for their required subset of agents.  Moreover, inside these functions they can add and remove components as needed.  (In more advanced implementations, the addition and removal of components is a scheduled process that occurs after every other system has run its `update` step to avoid errors.

## DES
Discrete-event simulations operate with many processes happening asynchronously, with various inter-process communications and message passing happening at arbitrary times.  They maintain an event queue as a priority queue with time as the prioritization, with ties broken by push order.  To move time forward, events are "popped" from the queue, marked as "triggered", and then execute a series of registered callbacks (that may or may not push more events into the event queue).

This leads to simulation architecture where many processes start running and schedule events based on shared conditional logics, etc.  For example, you can easily have messages, events, and other shared statuses across anything in the simulation.

## Finding common ground

The compromise I struck between the two is to construct an event-triggered game loop:  systems will return a `simpy.Event` which is "triggered" when that system would like to initiate another execution of the game loop.  In the main game loop, rather than progressing time by fixed time steps, the loop "waits" after each execution to be prompted by one of the asynchronous processes started by the `System`s that are manipulating the data.

Because `simpy` executes its asynchronous processes using concurrency and `yield`s in Python, we don't have to worry about full lock-ing/threading/async as in other languages.  The main "sim loop" looks only slightly different:

```
while env.now < MAX_TIME:
    events = []
    for system in systems:
        events.append(system.update(ecs))
    
    yield AnyOf(events)
```
The `yield AnyOf` here (pseudocode for `simpy`) causes us to wait until any of the events returned by the `System`s are "triggered" before executing the main simulation loop again.  Time here, rather than being managed by the loop, is managed by the event queue marching along.

Within a `System.update` function, we have to start the async processes and return them to the main simulation loop.  I do this by having `startup` and `cleanup` processes, where the `cleanup` process `yield`s to the `startup`, and the main loop is given the `cleanup` process to `yield`.  This sequence guarantees that when the process defining the relevant logic in `startup` "triggers", the `cleanup` is called _first_, followed by the main simulation loop.


### Databases for sim outputs
One other change was to switch to using `SQLite` for the data outputs rather than managing an ever-growing list of data.  The benefit (in my opinion) is that as the simulation gets larger, the data can be "dumped" to the output file as a regularly-occuring event.  The transition to an ECS architecture also makes it much simpler to access and dump simulation outputs as needed--they are just the components!  They even have a natural "hierarchy" or "namespace" to them, with `Entity > Component > Attribute > Value`.

### Leaving Python...?
This project has been fun but it has also left me wondering if there's a world where I build a similar architecture in a much faster programming language.  There are crates that perform discrete-event simulation in rust like Asynchronix or and many crates that implement lightning fast ECS architectures such as bevy-ecs or specs, so I could just as easily implement this same event-driven loop mechanism in Rust and run the simulation at way faster speeds...