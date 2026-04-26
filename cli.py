"""
cli.py
──────
Interactive terminal runner for the Payment Collection Agent.

Usage
-----
    python cli.py

Type 'quit' or 'exit' to end the session.
"""

from agent import Agent


DIVIDER = "─" * 50


def main() -> None:
    print(f"\n{DIVIDER}")
    print("  Payment Collection Agent  (type 'quit' to exit)")
    print(DIVIDER)

    agent = Agent()

    # Send a greeting to trigger the opening message
    opening = agent.next("Hello")
    print(f"\nAgent: {opening['message']}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Session ended by user. Goodbye!")
            break

        if not user_input:
            continue

        response = agent.next(user_input)
        print(f"\nAgent: {response['message']}\n")


if __name__ == "__main__":
    main()