---
name: python-design-pattern
description: "Knowledge base of Python Design Patterns from faif/python-patterns. Covers Creational, Structural, and Behavioral patterns with Python-specific idioms."
---

# Python Design Patterns
**Source**: faif/python-patterns | **Patterns**: 39 | **Generated**: 2026-08-26

## How to Use This Skill

- **Without arguments** — load core frameworks for reference
- **With a topic** — ask about a pattern (e.g. `factory`, `observer`); I find and read the relevant chapter
- **With chapter** — ask for `ch01`; I load that specific chapter

---

## Core Categories

1. **Creational Patterns**: Deal with object creation (abstracting and controlling how instances are made).
2. **Structural Patterns**: Define how classes and objects are composed to form larger structures.
3. **Behavioral Patterns**: Concerned with communication and responsibility between objects.

---

## Chapter Index

| # | Title (Category) | Description |
|---|------------------|-------------|
| [ch01](chapters/ch01-abstract_factory.md) | Abstract Factory (Creational Patterns) | use a generic function with specific factories |
| [ch02](chapters/ch02-borg.md) | Borg (Creational Patterns) | a singleton with shared-state among instances |
| [ch03](chapters/ch03-builder.md) | Builder (Creational Patterns) | instead of using multiple constructors, builder object receives parameters and returns constructed objects |
| [ch04](chapters/ch04-factory.md) | Factory (Creational Patterns) | delegate a specialized function/method to create instances |
| [ch05](chapters/ch05-lazy_evaluation.md) | Lazy Evaluation (Creational Patterns) | lazily-evaluated property pattern in Python |
| [ch06](chapters/ch06-pool.md) | Pool (Creational Patterns) | preinstantiate and maintain a group of instances of the same type |
| [ch07](chapters/ch07-prototype.md) | Prototype (Creational Patterns) | use a factory and clones of a prototype for new instances (if instantiation is expensive) |
| [ch08](chapters/ch08-3-tier.md) | 3-Tier (Structural Patterns) | data<->business logic<->presentation separation (strict relationships) |
| [ch09](chapters/ch09-adapter.md) | Adapter (Structural Patterns) | adapt one interface to another using a white-list |
| [ch10](chapters/ch10-bridge.md) | Bridge (Structural Patterns) | a client-provider middleman to soften interface changes |
| [ch11](chapters/ch11-composite.md) | Composite (Structural Patterns) | lets clients treat individual objects and compositions uniformly |
| [ch12](chapters/ch12-decorator.md) | Decorator (Structural Patterns) | wrap functionality with other functionality in order to affect outputs |
| [ch13](chapters/ch13-facade.md) | Facade (Structural Patterns) | use one class as an API to a number of others |
| [ch14](chapters/ch14-flyweight.md) | Flyweight (Structural Patterns) | transparently reuse existing instances of objects with similar/identical state |
| [ch15](chapters/ch15-front_controller.md) | Front Controller (Structural Patterns) | single handler requests coming to the application |
| [ch16](chapters/ch16-mvc.md) | Mvc (Structural Patterns) | model<->view<->controller (non-strict relationships) |
| [ch17](chapters/ch17-proxy.md) | Proxy (Structural Patterns) | an object funnels operations to something else |
| [ch18](chapters/ch18-chain_of_responsibility.md) | Chain Of Responsibility (Behavioral Patterns) | apply a chain of successive handlers to try and process the data |
| [ch19](chapters/ch19-catalog.md) | Catalog (Behavioral Patterns) | general methods will call different specialized methods based on construction parameter |
| [ch20](chapters/ch20-chaining_method.md) | Chaining Method (Behavioral Patterns) | continue callback next object method |
| [ch21](chapters/ch21-command.md) | Command (Behavioral Patterns) | bundle a command and arguments to call later |
| [ch22](chapters/ch22-iterator.md) | Iterator (Behavioral Patterns) | traverse a container and access the container's elements |
| [ch23](chapters/ch23-iterator.md) | Iterator (Behavioral Patterns) | traverse a container and access the container's elements |
| [ch24](chapters/ch24-mediator.md) | Mediator (Behavioral Patterns) | an object that knows how to connect other objects and act as a proxy |
| [ch25](chapters/ch25-memento.md) | Memento (Behavioral Patterns) | generate an opaque token that can be used to go back to a previous state |
| [ch26](chapters/ch26-observer.md) | Observer (Behavioral Patterns) | provide a callback for notification of events/changes to data |
| [ch27](chapters/ch27-publish_subscribe.md) | Publish Subscribe (Behavioral Patterns) | a source syndicates events/data to 0+ registered listeners |
| [ch28](chapters/ch28-registry.md) | Registry (Behavioral Patterns) | keep track of all subclasses of a given class |
| [ch29](chapters/ch29-servant.md) | Servant (Behavioral Patterns) | provide common functionality to a group of classes without using inheritance |
| [ch30](chapters/ch30-specification.md) | Specification (Behavioral Patterns) | business rules can be recombined by chaining the business rules together using boolean logic |
| [ch31](chapters/ch31-state.md) | State (Behavioral Patterns) | logic is organized into a discrete number of potential states and the next state that can be transitioned to |
| [ch32](chapters/ch32-strategy.md) | Strategy (Behavioral Patterns) | selectable operations over the same data |
| [ch33](chapters/ch33-template.md) | Template (Behavioral Patterns) | an object imposes a structure but takes pluggable components |
| [ch34](chapters/ch34-visitor.md) | Visitor (Behavioral Patterns) | invoke a callback for all items of a collection |
| [ch35](chapters/ch35-dependency_injection.md) | Dependency Injection (Design for Testability Patterns) | 3 variants of dependency injection |
| [ch36](chapters/ch36-delegation_pattern.md) | Delegation Pattern (Fundamental Patterns) | an object handles a request by delegating to a second object (the delegate) |
| [ch37](chapters/ch37-blackboard.md) | Blackboard (Others) | architectural model, assemble different sub-system knowledge to build a solution, AI approach - non gang of four pattern |
| [ch38](chapters/ch38-graph_search.md) | Graph Search (Others) | graphing algorithms - non gang of four pattern |
| [ch39](chapters/ch39-hsm.md) | Hsm (Others) | hierarchical state machine - non gang of four pattern |

## Topic Index

- **abstract_factory** → ch01
- **borg** → ch02
- **builder** → ch03
- **factory** → ch04
- **lazy_evaluation** → ch05
- **pool** → ch06
- **prototype** → ch07
- **3-tier** → ch08
- **adapter** → ch09
- **bridge** → ch10
- **composite** → ch11
- **decorator** → ch12
- **facade** → ch13
- **flyweight** → ch14
- **front_controller** → ch15
- **mvc** → ch16
- **proxy** → ch17
- **chain_of_responsibility** → ch18
- **catalog** → ch19
- **chaining_method** → ch20
- **command** → ch21
- **iterator** → ch22
- **iterator** → ch23
- **mediator** → ch24
- **memento** → ch25
- **observer** → ch26
- **publish_subscribe** → ch27
- **registry** → ch28
- **servant** → ch29
- **specification** → ch30
- **state** → ch31
- **strategy** → ch32
- **template** → ch33
- **visitor** → ch34
- **dependency_injection** → ch35
- **delegation_pattern** → ch36
- **blackboard** → ch37
- **graph_search** → ch38
- **hsm** → ch39

## Supporting Files

- [glossary.md](glossary.md) — all key patterns with short descriptions
- [patterns.md](patterns.md) — pattern techniques
- [cheatsheet.md](cheatsheet.md) — quick reference

