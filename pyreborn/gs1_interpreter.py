#!/usr/bin/env python3
"""
Basic GS1 (GS1) interpreter for pyreborn.
Handles simple client-side scripts.

GS1 is a simple scripting language with:
- Event handlers: if (playerenters) { ... }
- Commands: say, setcoloreffect, drawaslight, etc.
- Variables: this.varname, player.varname
"""

import re
import time
from typing import Dict, Any, Callable, Optional, List


class GS1Interpreter:
    """Simple GS1 script interpreter."""

    def __init__(self, client=None):
        self.client = client
        self.variables: Dict[str, Any] = {}
        self.this_vars: Dict[str, Any] = {}
        self.scripts: Dict[str, str] = {}  # name -> script code
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.script_timeouts: Dict[str, float] = {}  # script -> expire time
        self.current_script: Optional[str] = None  # Track which script is executing

        # Built-in commands
        self.commands = {
            'say': self.cmd_say,
            'setani': self.cmd_setani,
            'setcoloreffect': self.cmd_setcoloreffect,
            'drawaslight': self.cmd_drawaslight,
            'hidelocal': self.cmd_hidelocal,
            'showlocal': self.cmd_showlocal,
            'timeout': self.cmd_timeout,
            'setstring': self.cmd_setstring,
            'tokenize': self.cmd_tokenize,
            'message': self.cmd_message,
        }

    def load_script(self, name: str, code: str):
        """Load a script by name."""
        # Convert GS1 section markers
        code = code.replace('§', '\n')
        self.scripts[name] = code
        print(f"  Loaded script: {name} ({len(code)} bytes)")

    def parse_script(self, code: str) -> List[dict]:
        """Parse script into event blocks with proper brace matching."""
        blocks = []

        # Find if (...) pattern and match braces properly
        pattern = r'if\s*\(([^)]+)\)\s*\{'
        for match in re.finditer(pattern, code, re.DOTALL):
            condition = match.group(1).strip()
            start = match.end()

            # Count braces to find matching close brace
            brace_count = 1
            pos = start
            while pos < len(code) and brace_count > 0:
                if code[pos] == '{':
                    brace_count += 1
                elif code[pos] == '}':
                    brace_count -= 1
                pos += 1

            body = code[start:pos - 1].strip()
            blocks.append({
                'condition': condition,
                'body': body
            })

        return blocks

    def evaluate_condition(self, condition: str) -> bool:
        """Evaluate a condition string."""
        orig_condition = condition
        condition = condition.strip()

        # Handle negation
        if condition.startswith('!'):
            inner = condition[1:].strip()
            if inner.startswith('(') and inner.endswith(')'):
                inner = inner[1:-1]
            return not self.evaluate_condition(inner)

        # Handle || (OR)
        if '||' in condition:
            parts = condition.split('||')
            return any(self.evaluate_condition(p.strip()) for p in parts)

        # Handle && (AND)
        if '&&' in condition:
            parts = condition.split('&&')
            return all(self.evaluate_condition(p.strip()) for p in parts)

        # Simple event conditions
        condition_lower = condition.lower()

        if 'playerenters' in condition_lower:
            return True  # Trigger on load
        if 'timeout' in condition_lower:
            return False  # Need timeout system
        if 'playerchats' in condition_lower:
            return False  # Need chat trigger

        # Variable check (e.g., "gr.off" checks if var is truthy)
        if '.' in condition:
            var_name = condition.strip()
            value = self.variables.get(var_name, self.this_vars.get(var_name))
            return bool(value)

        return False

    def execute_body(self, body: str, context: dict = None):
        """Execute script body (series of commands)."""
        if context is None:
            context = {}

        lines = body.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line or line.startswith('//'):
                continue

            # Handle nested if blocks
            if line.startswith('if ') or line.startswith('if('):
                # Check if this is a single-line if (no brace) or multi-line (has brace)
                if '{' in line:
                    # Multi-line: find matching closing brace
                    brace_count = line.count('{') - line.count('}')
                    block_lines = [line]

                    while brace_count > 0 and i < len(lines):
                        block_lines.append(lines[i])
                        brace_count += lines[i].count('{') - lines[i].count('}')
                        i += 1

                    # Parse and potentially execute the nested if
                    nested_code = '\n'.join(block_lines)
                    nested_blocks = self.parse_script(nested_code)
                    for block in nested_blocks:
                        if self.evaluate_condition(block['condition']):
                            self.execute_body(block['body'], context)
                else:
                    # Single-line if: if (condition) command;
                    match = re.match(r'if\s*\(([^)]+)\)\s*(.+)', line)
                    if match:
                        condition = match.group(1).strip()
                        command = match.group(2).strip()
                        if self.evaluate_condition(condition):
                            self.execute_command(command, context)
                continue

            # Remove trailing semicolon
            if line.endswith(';'):
                line = line[:-1]

            self.execute_command(line, context)

    def execute_command(self, line: str, context: dict = None):
        """Execute a single command."""
        if not line:
            return

        # Handle assignment syntax (e.g., timeout=0.05, this.var=value)
        if '=' in line and not line.startswith('if'):
            parts = line.split('=', 1)
            var_name = parts[0].strip()
            value = parts[1].strip()

            # Special case: timeout assignment
            if var_name.lower() == 'timeout':
                self.cmd_timeout([value], context)
                return

            # Variable assignment
            if var_name.startswith('this.'):
                self.this_vars[var_name] = value
            else:
                self.variables[var_name] = value
            return

        # Parse command and arguments
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ''

        # Parse arguments (comma-separated)
        args = [a.strip() for a in args_str.split(',')] if args_str else []

        if cmd in self.commands:
            try:
                self.commands[cmd](args, context)
            except Exception as e:
                print(f"    Error in {cmd}: {e}")
        else:
            pass  # Silently ignore unknown commands in production

    def trigger_event(self, event: str, context: dict = None):
        """Trigger an event and run matching scripts."""
        if context is None:
            context = {}

        for name, code in self.scripts.items():
            blocks = self.parse_script(code)
            for block in blocks:
                if event.lower() in block['condition'].lower():
                    self.current_script = name
                    self.execute_body(block['body'], context)
                    self.current_script = None

    def update(self):
        """Check for expired timeouts and trigger them."""
        now = time.time()
        expired = []

        for script_name, expire_time in self.script_timeouts.items():
            if now >= expire_time:
                expired.append(script_name)

        for script_name in expired:
            del self.script_timeouts[script_name]
            if script_name in self.scripts:
                code = self.scripts[script_name]
                blocks = self.parse_script(code)
                for block in blocks:
                    if 'timeout' in block['condition'].lower():
                        self.current_script = script_name
                        self.execute_body(block['body'], {})
                        self.current_script = None

    # =========================================================================
    # Commands
    # =========================================================================

    def cmd_say(self, args: List[str], context: dict):
        """say message - send chat message."""
        if args:
            message = ' '.join(args)
            print(f"    [SAY] {message}")
            if self.client:
                self.client.say(message)

    def cmd_setani(self, args: List[str], context: dict):
        """setani animation - set player animation."""
        if args:
            ani = args[0]
            print(f"    [SETANI] {ani}")

    def cmd_setcoloreffect(self, args: List[str], context: dict):
        """setcoloreffect r,g,b,a - set color effect."""
        pass  # Visual effect - would be handled by renderer

    def cmd_drawaslight(self, args: List[str], context: dict):
        """drawaslight - draw NPC as light source."""
        pass  # Visual effect - would be handled by renderer

    def cmd_hidelocal(self, args: List[str], context: dict):
        """hidelocal - hide locally."""
        print(f"    [HIDELOCAL]")

    def cmd_showlocal(self, args: List[str], context: dict):
        """showlocal - show locally."""
        print(f"    [SHOWLOCAL]")

    def cmd_timeout(self, args: List[str], context: dict):
        """timeout seconds - set timeout for current script."""
        if args and self.current_script:
            try:
                seconds = float(args[0])
                self.script_timeouts[self.current_script] = time.time() + seconds
            except ValueError:
                pass

    def cmd_setstring(self, args: List[str], context: dict):
        """setstring name,value - set string variable."""
        if len(args) >= 2:
            name = args[0]
            value = ','.join(args[1:])

            # Evaluate special values
            value = self.evaluate_expression(value)

            self.variables[name] = value

    def evaluate_expression(self, expr: str) -> str:
        """Evaluate a GS1 expression."""
        # Handle #v() - evaluate numeric expression with proper parenthesis matching
        if '#v(' in expr:
            start = expr.find('#v(')
            if start != -1:
                # Find matching close paren
                paren_start = start + 3
                paren_count = 1
                pos = paren_start
                while pos < len(expr) and paren_count > 0:
                    if expr[pos] == '(':
                        paren_count += 1
                    elif expr[pos] == ')':
                        paren_count -= 1
                    pos += 1

                inner = expr[paren_start:pos - 1]
                # Handle playerx, playery
                if 'playerx' in inner and self.client:
                    inner = inner.replace('playerx', str(self.client.x % 64))
                if 'playery' in inner and self.client:
                    inner = inner.replace('playery', str(self.client.y % 64))
                try:
                    result = eval(inner)
                    return str(result)
                except Exception as e:
                    pass
        return expr

    def cmd_tokenize(self, args: List[str], context: dict):
        """tokenize string - tokenize string."""
        if args:
            print(f"    [TOKENIZE] {args[0]}")

    def cmd_message(self, args: List[str], context: dict):
        """message text - show message."""
        if args:
            print(f"    [MESSAGE] {' '.join(args)}")


def test_interpreter():
    """Test the GS1 interpreter."""
    print("=== GS1 Interpreter Test ===\n")

    interp = GS1Interpreter()

    # Test script 1: Simple light NPC
    script1 = """//#CLIENTSIDE
if (playerenters) {
setcoloreffect 1,1,1,0.99;
drawaslight;
}"""

    interp.load_script("light_npc", script1)

    # Test script 2: Movement weapon
    script2 = """//#CLIENTSIDE
if (playerenters || timeout) {
if (!gr.off) {
say Hello World;
timeout 1;
}
}"""

    interp.load_script("movement", script2)

    print("\n=== Triggering playerenters ===")
    interp.trigger_event("playerenters")

    print("\n=== Triggering timeout ===")
    interp.trigger_event("timeout")


if __name__ == "__main__":
    test_interpreter()
