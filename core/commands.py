from core.utils import send_system_message

class CommandDispatcher:
    def __init__(self):
        self.registry = {}

    def command(self, name):
        """Decorator to register a function as a command."""
        def decorator(func):
            self.registry[name.lower()] = func
            return func
        return decorator

    def process(self, ctx, message):
        """Parses the message and executes the matching command."""
        if not message: return False

        # Split into ["command", "arg1", "arg2"...]
        parts = message.strip().split()
        cmd_name = parts[0].lower()
        args = parts[1:]

        if cmd_name in self.registry:
            try:
                # Call the function with (ctx, *args)
                self.registry[cmd_name](ctx, *args)
                return True
            except TypeError as e:
                # This handles cases where user typed wrong number of args
                print(f"[Command Error] {e}")
                send_system_message(ctx, "Invalid arguments for command.")
                return True
            except Exception as e:
                print(f"[Command Error] {e}")
                send_system_message(ctx, "Command execution failed.")
                return True
        
        return False

# Global instance
commands = CommandDispatcher()