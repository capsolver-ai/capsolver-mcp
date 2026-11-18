"""Independent browser entry point; no CapSolver API key or paid operations."""


def main() -> None:
    from capsolver_mcp.__main__ import main as run

    run(default_mode="browser")


if __name__ == "__main__":
    main()
