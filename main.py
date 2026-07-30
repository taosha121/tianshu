from agent import Agent


def main():
    agent = Agent()
    print("灵机一动 Agent 启动")
    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        response = agent.chat(user_input)
        print(f"Agent: {response}")


if __name__ == "__main__":
    main()
