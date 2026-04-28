"""Human-in-the-loop policy for terminal play."""

from __future__ import annotations

from typing import IO, Any, Protocol


class HumanQuit(BaseException):
    """Sentinel raised when the human seat declines a turn."""

    def __init__(self, reason: str = "user_quit") -> None:
        super().__init__(reason)
        self.reason = reason


class _Parser(Protocol):
    def __call__(self, line: str, observation: Any) -> Any | None: ...


class HumanPolicy:
    """Read one action per turn from an injected stdin stream."""

    def __init__(
        self,
        parser: _Parser,
        *,
        stdin: IO[str],
        stdout: IO[str],
        prompt: str = "Your move: ",
    ) -> None:
        self._parser = parser
        self._stdin = stdin
        self._stdout = stdout
        self._prompt = prompt

    def select_action(self, observation: Any) -> Any:
        while True:
            self._stdout.write(self._prompt)
            self._stdout.flush()
            try:
                line = self._stdin.readline()
            except KeyboardInterrupt:
                raise HumanQuit("user_interrupt")

            if line == "":
                raise HumanQuit("user_quit")

            stripped = line.strip().lower()
            if stripped in {"q", "quit"}:
                raise HumanQuit("user_quit")

            action = self._parser(line, observation)
            if action is not None:
                return action

            self._stdout.write("Invalid input. Try again.\n")
            self._stdout.flush()


__all__: tuple[str, ...] = ("HumanPolicy", "HumanQuit")
