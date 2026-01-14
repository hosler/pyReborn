#!/usr/bin/env python3
"""
GS1 interpreter for pyreborn.
Full implementation of client-side Reborn Script 1.

Supports:
- Event handlers: playerenters, playertouchsme, timeout, playerchats
- Control flow: if/else, for, while, break, continue
- Functions: function Name() { } and calls
- Variables: this.var, #varname, #s(string), #a (account), #c (chat)
- Arrays: setarray, tokenize, tokenscount, #t(index), #I(array,index)
- String functions: strequals, strlen, strtofloat, sarraylen
- Commands: triggeraction, setplayerprop, setcharprop, play, showimg, etc.
"""

import re
import time
import math
from typing import Dict, Any, Callable, Optional, List, Tuple


class GS1Interpreter:
    """Full GS1 script interpreter."""

    def __init__(self, client=None):
        self.client = client

        # Variable storage
        self.variables: Dict[str, Any] = {}
        self.this_vars: Dict[str, Any] = {}  # this.* variables per NPC
        self.npc_char_props: Dict[str, str] = {}  # #P1, #P2, #P3, etc
        self.server_strings: Dict[str, str] = {}  # #s(name) strings
        self.client_strings: Dict[str, str] = {}  # client.* strings

        # Arrays and tokens
        self.arrays: Dict[str, List[Any]] = {}
        self.tokens: List[str] = []  # Current tokenized list
        self.save: List[Any] = [0] * 100  # save[] array
        self.clientr: Dict[str, Any] = {}  # clientr.* variables

        # Scripts and state
        self.scripts: Dict[str, str] = {}  # name -> script code
        self.script_timeouts: Dict[str, float] = {}  # script -> expire time
        self.current_script: Optional[str] = None
        self.current_npc_id: int = 0
        self.current_npc_x: float = 0.0
        self.current_npc_y: float = 0.0

        # Function definitions
        self.functions: Dict[str, Tuple[str, str]] = {}  # name -> (params, body)

        # Control flow
        self.break_flag = False
        self.continue_flag = False

        # Images and effects
        self.shown_images: Dict[int, dict] = {}
        self.default_movement_enabled = True
        self.player_frozen = False
        self.freeze_until = 0.0

        # Callbacks
        self.on_showimg: Optional[Callable[[int, str, float, float], None]] = None
        self.on_hideimg: Optional[Callable[[int], None]] = None
        self.on_play: Optional[Callable[[str], None]] = None
        self.on_say: Optional[Callable[[int, str], None]] = None  # (npc_id, message)
        self.on_message: Optional[Callable[[str], None]] = None
        self.on_setmap: Optional[Callable[[str, str, int, int], None]] = None
        self.on_movement_changed: Optional[Callable[[bool], None]] = None
        self.on_triggeraction: Optional[Callable[[float, float, str, int], None]] = None
        self.on_setplayerprop: Optional[Callable[[str, str], None]] = None
        self.on_shoot: Optional[Callable[[str, List[str]], None]] = None

    def load_script(self, name: str, code: str, npc_id: int = 0, x: float = 0, y: float = 0):
        """Load a script with NPC context."""
        code = code.replace('§', '\n')
        self.scripts[name] = code

        # Parse function definitions from the script
        self._parse_functions(code)

    def _parse_functions(self, code: str):
        """Parse function definitions from code."""
        pattern = r'function\s+(\w+)\s*\(\s*\)\s*\{'
        for match in re.finditer(pattern, code):
            func_name = match.group(1)
            start = match.end()

            # Find matching brace
            brace_count = 1
            pos = start
            while pos < len(code) and brace_count > 0:
                if code[pos] == '{':
                    brace_count += 1
                elif code[pos] == '}':
                    brace_count -= 1
                pos += 1

            body = code[start:pos-1].strip()
            self.functions[func_name] = ('', body)

    def parse_blocks(self, code: str) -> List[dict]:
        """Parse if blocks from code."""
        blocks = []
        pattern = r'if\s*\(([^)]+)\)\s*\{'

        for match in re.finditer(pattern, code, re.DOTALL):
            condition = match.group(1).strip()
            start = match.end()

            brace_count = 1
            pos = start
            while pos < len(code) and brace_count > 0:
                if code[pos] == '{':
                    brace_count += 1
                elif code[pos] == '}':
                    brace_count -= 1
                pos += 1

            body = code[start:pos-1].strip()
            blocks.append({'condition': condition, 'body': body})

        return blocks

    def evaluate_condition(self, condition: str) -> bool:
        """Evaluate a GS1 condition."""
        condition = condition.strip()

        # Handle negation
        if condition.startswith('!'):
            inner = condition[1:].strip()
            if inner.startswith('(') and inner.endswith(')'):
                inner = inner[1:-1]
            return not self.evaluate_condition(inner)

        # Handle parentheses
        if condition.startswith('(') and condition.endswith(')'):
            return self.evaluate_condition(condition[1:-1])

        # Handle || (OR) - split carefully
        or_parts = self._split_logical(condition, '||')
        if len(or_parts) > 1:
            return any(self.evaluate_condition(p.strip()) for p in or_parts)

        # Handle && (AND)
        and_parts = self._split_logical(condition, '&&')
        if len(and_parts) > 1:
            return all(self.evaluate_condition(p.strip()) for p in and_parts)

        # Handle comparison operators
        for op in ['==', '!=', '<=', '>=', '<>', '<', '>']:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    left = self.evaluate_expression(parts[0].strip())
                    right = self.evaluate_expression(parts[1].strip())

                    # Try numeric comparison
                    try:
                        left_num = float(left) if left else 0
                        right_num = float(right) if right else 0
                        if op == '==':
                            return left_num == right_num
                        elif op in ('!=', '<>'):
                            return left_num != right_num
                        elif op == '<':
                            return left_num < right_num
                        elif op == '>':
                            return left_num > right_num
                        elif op == '<=':
                            return left_num <= right_num
                        elif op == '>=':
                            return left_num >= right_num
                    except (ValueError, TypeError):
                        # String comparison
                        if op == '==':
                            return str(left) == str(right)
                        elif op in ('!=', '<>'):
                            return str(left) != str(right)
                    return False

        # Handle function calls in conditions
        if condition.startswith('strequals('):
            return self._func_strequals(condition)

        # Handle simple event names
        condition_lower = condition.lower()
        if 'playerenters' in condition_lower:
            return True
        if 'playertouchsme' in condition_lower:
            return self.variables.get('_playertouchsme', False)
        if 'timeout' in condition_lower:
            return self.variables.get('_timeout', False)
        if 'playerchats' in condition_lower:
            return self.variables.get('_playerchats', False)
        if 'playerdir' in condition_lower:
            # playerdir == X check
            match = re.search(r'playerdir\s*==\s*(\d+)', condition)
            if match:
                required = int(match.group(1))
                current = self.get_variable('playerdir')
                return current == required

        # Check if it's a truthy variable
        value = self.evaluate_expression(condition)
        try:
            return bool(float(value)) if value else False
        except (ValueError, TypeError):
            return bool(value)

    def _split_logical(self, s: str, op: str) -> List[str]:
        """Split by logical operator respecting parentheses."""
        parts = []
        current = []
        depth = 0
        i = 0
        while i < len(s):
            if s[i] == '(':
                depth += 1
            elif s[i] == ')':
                depth -= 1
            elif depth == 0 and s[i:i+len(op)] == op:
                parts.append(''.join(current))
                current = []
                i += len(op)
                continue
            current.append(s[i])
            i += 1
        parts.append(''.join(current))
        return parts

    def evaluate_expression(self, expr: str) -> Any:
        """Evaluate a GS1 expression and return its value."""
        if expr is None:
            return ''

        expr = str(expr).strip()

        # Empty string
        if not expr:
            return ''

        # Quoted strings
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        # Handle #a - account name
        if expr == '#a':
            if self.client:
                return self.client.player.account or ''
            return ''

        # Handle #c - current chat message
        if expr == '#c':
            return self.variables.get('player_chat', '')

        # Handle #s(name) - server string
        if expr.startswith('#s(') and ')' in expr:
            match = re.match(r'#s\(([^)]+)\)', expr)
            if match:
                name = match.group(1)
                return self.server_strings.get(name, '')

        # Handle #t(index) - token access
        if expr.startswith('#t(') and ')' in expr:
            match = re.match(r'#t\(([^)]+)\)', expr)
            if match:
                idx_expr = match.group(1)
                try:
                    idx = int(self.evaluate_expression(idx_expr))
                    if 0 <= idx < len(self.tokens):
                        return self.tokens[idx]
                except (ValueError, IndexError):
                    pass
                return ''

        # Handle #I(array,index) - array/string index
        if expr.startswith('#I(') and ')' in expr:
            match = re.match(r'#I\(([^,]+),(\d+)\)', expr)
            if match:
                arr_name = match.group(1)
                idx = int(match.group(2))
                arr_val = self.get_variable(arr_name)
                if isinstance(arr_val, str):
                    # Split by comma and get index
                    parts = arr_val.split(',')
                    if 0 <= idx < len(parts):
                        return parts[idx].strip()
                return ''

        # Handle #P1, #P2, #P3 - char props
        if expr.startswith('#P') and len(expr) >= 3:
            match = re.match(r'#P(\d+)(\(-1\))?', expr)
            if match:
                prop_num = match.group(1)
                key = f'P{prop_num}'
                return self.npc_char_props.get(key, '')

        # Handle #v(expr) - numeric value
        if expr.startswith('#v(') and ')' in expr:
            inner = self._extract_parens(expr, 3)
            try:
                # Substitute variables
                inner = self._substitute_vars(inner)
                result = eval(inner)
                return str(int(result)) if isinstance(result, float) and result.is_integer() else str(result)
            except:
                return '0'

        # Handle #e(start,count,sep)expr - conditional expression
        if expr.startswith('#e('):
            return self._eval_conditional_expr(expr)

        # Handle tokenscount
        if expr == 'tokenscount':
            return len(self.tokens)

        # Handle playerscount
        if expr == 'playerscount':
            if self.client:
                return len(self.client.players) + 1
            return 1

        # Handle timevar
        if expr == 'timevar':
            return int(time.time())

        # Handle x, y (NPC position)
        if expr == 'x':
            return self.current_npc_x
        if expr == 'y':
            return self.current_npc_y

        # Handle playerx, playery
        if expr == 'playerx':
            if self.client:
                return self.client.x % 64
            return 0
        if expr == 'playery':
            if self.client:
                return self.client.y % 64
            return 0

        # Handle function calls
        if '(' in expr and ')' in expr:
            func_match = re.match(r'(\w+)\s*\(([^)]*)\)', expr)
            if func_match:
                func_name = func_match.group(1).lower()
                args_str = func_match.group(2)

                if func_name == 'strlen':
                    arg = self.evaluate_expression(args_str.strip())
                    return len(str(arg))
                elif func_name == 'strtofloat':
                    arg = self.evaluate_expression(args_str.strip())
                    try:
                        return float(arg)
                    except:
                        return 0.0
                elif func_name == 'int':
                    arg = self.evaluate_expression(args_str.strip())
                    try:
                        return int(float(arg))
                    except:
                        return 0
                elif func_name == 'random':
                    parts = args_str.split(',')
                    if len(parts) >= 2:
                        low = float(self.evaluate_expression(parts[0].strip()))
                        high = float(self.evaluate_expression(parts[1].strip()))
                        import random
                        return random.uniform(low, high)
                    return 0
                elif func_name == 'sarraylen':
                    arr_name = args_str.strip()
                    arr_val = self.get_variable(arr_name)
                    if isinstance(arr_val, str):
                        return len([p for p in arr_val.split(',') if p.strip()])
                    return 0
                elif func_name == 'abs':
                    arg = self.evaluate_expression(args_str.strip())
                    try:
                        return abs(float(arg))
                    except:
                        return 0

        # Try numeric literal
        try:
            if '.' in expr:
                return float(expr)
            return int(expr)
        except ValueError:
            pass

        # Handle arithmetic expressions (e.g., x+2, playerx-1)
        for op in ['+', '-', '*', '/', '%']:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = self.evaluate_expression(parts[0].strip())
                    right = self.evaluate_expression(parts[1].strip())
                    try:
                        left_num = float(left) if left else 0
                        right_num = float(right) if right else 0
                        if op == '+':
                            return left_num + right_num
                        elif op == '-':
                            return left_num - right_num
                        elif op == '*':
                            return left_num * right_num
                        elif op == '/':
                            return left_num / right_num if right_num != 0 else 0
                        elif op == '%':
                            return left_num % right_num if right_num != 0 else 0
                    except (ValueError, TypeError):
                        pass

        # Variable lookup
        return self.get_variable(expr)

    def _extract_parens(self, s: str, start: int) -> str:
        """Extract content within parentheses starting at position."""
        depth = 1
        pos = start
        while pos < len(s) and depth > 0:
            if s[pos] == '(':
                depth += 1
            elif s[pos] == ')':
                depth -= 1
            pos += 1
        return s[start:pos-1]

    def _substitute_vars(self, expr: str) -> str:
        """Substitute variable names with their values."""
        # Replace this.varname
        for var in list(self.this_vars.keys()):
            if var in expr:
                expr = expr.replace(var, str(self.this_vars[var]))

        # Replace simple variables
        for var in ['playerx', 'playery', 'x', 'y']:
            if var in expr:
                expr = expr.replace(var, str(self.evaluate_expression(var)))

        return expr

    def _eval_conditional_expr(self, expr: str) -> str:
        """Evaluate #e(start,count,sep)expr conditional expression."""
        # Format: #e(start_index, count, separator)value_if_true
        # If count > 0, returns the separator + value, otherwise returns start
        match = re.match(r'#e\((\d+),([^,]+),([^)]*)\)(.+)', expr)
        if match:
            start = int(match.group(1))
            count_expr = match.group(2)
            separator = match.group(3)
            value = match.group(4)

            count = self.evaluate_expression(count_expr)
            try:
                count = int(float(count))
            except:
                count = 0

            if count > 0:
                return separator + self.evaluate_expression(value)
            return ''
        return ''

    def _func_strequals(self, expr: str) -> bool:
        """Evaluate strequals(a,b) function."""
        match = re.match(r'strequals\s*\(([^,]+),([^)]+)\)', expr)
        if match:
            a = self.evaluate_expression(match.group(1).strip())
            b = self.evaluate_expression(match.group(2).strip())
            return str(a) == str(b)
        return False

    def get_variable(self, name: str) -> Any:
        """Get a variable value."""
        name = str(name).strip()

        # Handle save[]
        if name.startswith('save['):
            match = re.match(r'save\[(\d+)\]', name)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < len(self.save):
                    return self.save[idx]
            return 0

        # Handle clientr.*
        if name.startswith('clientr.'):
            return self.clientr.get(name[8:], '')

        # Handle client.*
        if name.startswith('client.'):
            return self.client_strings.get(name[7:], '')

        # Handle this.* - special case for x and y (NPC position)
        if name == 'this.x':
            return self.current_npc_x
        if name == 'this.y':
            return self.current_npc_y
        if name.startswith('this.'):
            return self.this_vars.get(name, 0)

        # Handle player properties
        if name == 'playerx' and self.client:
            return self.client.x % 64
        if name == 'playery' and self.client:
            return self.client.y % 64
        if name == 'playerdir' and self.client:
            return self.client.player.direction

        # Handle NPC position
        if name == 'x':
            return self.current_npc_x
        if name == 'y':
            return self.current_npc_y

        return self.variables.get(name, 0)

    def set_variable(self, name: str, value: Any):
        """Set a variable value."""
        name = str(name).strip()

        # Handle save[]
        if name.startswith('save['):
            match = re.match(r'save\[(\d+)\]', name)
            if match:
                idx = int(match.group(1))
                if 0 <= idx < len(self.save):
                    self.save[idx] = value
            return

        # Handle clientr.*
        if name.startswith('clientr.'):
            self.clientr[name[8:]] = value
            return

        # Handle client.*
        if name.startswith('client.'):
            self.client_strings[name[7:]] = value
            return

        # Handle this.*
        if name.startswith('this.'):
            self.this_vars[name] = value
            return

        self.variables[name] = value

    def execute_body(self, body: str, context: dict = None):
        """Execute a block of script code."""
        if context is None:
            context = {}

        lines = body.split('\n')
        i = 0

        while i < len(lines):
            if self.break_flag or self.continue_flag:
                break

            line = lines[i].strip()
            i += 1

            if not line or line.startswith('//'):
                continue

            # Handle for loops
            if line.startswith('for(') or line.startswith('for ('):
                i = self._execute_for_loop(lines, i - 1, context)
                continue

            # Handle while loops
            if line.startswith('while(') or line.startswith('while ('):
                i = self._execute_while_loop(lines, i - 1, context)
                continue

            # Handle if/else blocks
            if line.startswith('if(') or line.startswith('if ('):
                i = self._execute_if_block(lines, i - 1, context)
                continue

            # Handle break
            if line == 'break;' or line == 'break':
                self.break_flag = True
                return

            # Handle continue
            if line == 'continue;' or line == 'continue':
                self.continue_flag = True
                return

            # Handle function calls
            if re.match(r'\w+\s*\(\s*\)\s*;?', line):
                func_name = re.match(r'(\w+)\s*\(', line).group(1)
                if func_name in self.functions:
                    _, func_body = self.functions[func_name]
                    self.execute_body(func_body, context)
                    continue

            # Regular command
            if line.endswith(';'):
                line = line[:-1]
            self.execute_command(line, context)

    def _execute_for_loop(self, lines: List[str], start_idx: int, context: dict) -> int:
        """Execute a for loop and return new index."""
        line = lines[start_idx]

        # Parse for(init;condition;increment)
        match = re.match(r'for\s*\(([^;]*);([^;]*);([^)]*)\)\s*\{?', line)
        if not match:
            return start_idx + 1

        init = match.group(1).strip()
        condition = match.group(2).strip()
        increment = match.group(3).strip()

        # Find loop body
        body_lines = []
        brace_count = 1 if '{' in line else 0
        i = start_idx + 1

        if brace_count == 0 and i < len(lines) and lines[i].strip() == '{':
            brace_count = 1
            i += 1

        while i < len(lines) and brace_count > 0:
            l = lines[i]
            brace_count += l.count('{') - l.count('}')
            if brace_count > 0:
                body_lines.append(l)
            i += 1

        body = '\n'.join(body_lines)

        # Execute init
        if init:
            self.execute_command(init, context)

        # Loop
        max_iterations = 1000
        iterations = 0
        while iterations < max_iterations:
            if not self.evaluate_condition(condition):
                break

            self.break_flag = False
            self.continue_flag = False
            self.execute_body(body, context)

            if self.break_flag:
                self.break_flag = False
                break

            self.continue_flag = False

            # Execute increment
            if increment:
                self.execute_command(increment, context)

            iterations += 1

        return i

    def _execute_while_loop(self, lines: List[str], start_idx: int, context: dict) -> int:
        """Execute a while loop and return new index."""
        line = lines[start_idx]

        match = re.match(r'while\s*\(([^)]+)\)\s*\{?', line)
        if not match:
            return start_idx + 1

        condition = match.group(1).strip()

        # Find loop body
        body_lines = []
        brace_count = 1 if '{' in line else 0
        i = start_idx + 1

        if brace_count == 0 and i < len(lines) and lines[i].strip() == '{':
            brace_count = 1
            i += 1

        while i < len(lines) and brace_count > 0:
            l = lines[i]
            brace_count += l.count('{') - l.count('}')
            if brace_count > 0:
                body_lines.append(l)
            i += 1

        body = '\n'.join(body_lines)

        max_iterations = 1000
        iterations = 0
        while iterations < max_iterations and self.evaluate_condition(condition):
            self.break_flag = False
            self.continue_flag = False
            self.execute_body(body, context)

            if self.break_flag:
                self.break_flag = False
                break

            self.continue_flag = False
            iterations += 1

        return i

    def _execute_if_block(self, lines: List[str], start_idx: int, context: dict) -> int:
        """Execute an if/else block and return new index."""
        line = lines[start_idx]

        match = re.match(r'if\s*\(([^)]+)\)', line)
        if not match:
            return start_idx + 1

        condition = match.group(1).strip()
        after_condition = line[match.end():].strip()

        # Check if body is on same line (single-line if)
        body = None
        pending_else = None
        i = start_idx + 1

        if after_condition.startswith('{'):
            # Multi-line with braces: if(cond) { ... }
            body_lines = []
            brace_count = 1  # Start with 1 for the opening brace

            # Check if body is complete on same line (rare but possible)
            rest_of_line = after_condition[1:].strip()
            if rest_of_line:
                # Content on same line after opening brace
                for j, ch in enumerate(rest_of_line):
                    if ch == '{':
                        brace_count += 1
                    elif ch == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            body = rest_of_line[:j].strip()
                            # Check for else on same line
                            remaining = rest_of_line[j+1:].strip()
                            if remaining.startswith('else'):
                                # Will be handled below in else_branches collection
                                pass
                            break
                else:
                    # Didn't find closing brace, rest of line is part of body
                    body_lines.append(rest_of_line)

            # Collect remaining body lines
            if brace_count > 0:
                while i < len(lines) and brace_count > 0:
                    l = lines[i].strip()
                    found_close = False
                    # Count braces character by character
                    for j, ch in enumerate(l):
                        if ch == '{':
                            brace_count += 1
                        elif ch == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                # Found closing brace - take everything before it
                                if j > 0:
                                    body_lines.append(l[:j])
                                # Check for else on same line
                                remaining = l[j+1:].strip()
                                if remaining.startswith('else'):
                                    pending_else = remaining
                                i += 1
                                found_close = True
                                break
                    if found_close:
                        break
                    # Didn't find closing brace on this line
                    body_lines.append(l)
                    i += 1
                body = '\n'.join(body_lines)
        elif after_condition:
            # Single-line if without braces: if(cond) stmt;
            body = after_condition
        else:
            # Body on next line
            if i < len(lines):
                next_line = lines[i].strip()
                if next_line == '{':
                    i += 1
                    body_lines = []
                    brace_count = 1
                    while i < len(lines) and brace_count > 0:
                        l = lines[i]
                        brace_count += l.count('{') - l.count('}')
                        if brace_count > 0:
                            body_lines.append(l)
                        i += 1
                    body = '\n'.join(body_lines)
                else:
                    body = next_line
                    i += 1

        # Collect else/else if chain
        else_branches = []  # List of (condition, body) - None condition means else

        # Check if we have a pending else from the same line as closing brace
        if pending_else:
            next_line = pending_else
            pending_else = None
        elif i < len(lines):
            next_line = lines[i].strip()
        else:
            next_line = ''

        while next_line:
            if next_line.startswith('else if(') or next_line.startswith('else if ('):
                # else if branch
                elif_match = re.match(r'else\s+if\s*\(([^)]+)\)', next_line)
                if elif_match:
                    elif_cond = elif_match.group(1).strip()
                    elif_after = next_line[elif_match.end():].strip()
                    i += 1

                    if elif_after.startswith('{'):
                        elif_body_lines = []
                        brace_count = 1

                        # Collect body with character-by-character brace counting
                        while i < len(lines) and brace_count > 0:
                            l = lines[i].strip()
                            found_close = False
                            for j, ch in enumerate(l):
                                if ch == '{':
                                    brace_count += 1
                                elif ch == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        if j > 0:
                                            elif_body_lines.append(l[:j])
                                        remaining = l[j+1:].strip()
                                        if remaining.startswith('else'):
                                            pending_else = remaining
                                        i += 1
                                        found_close = True
                                        break
                            if found_close:
                                break
                            elif_body_lines.append(l)
                            i += 1
                        elif_body = '\n'.join(elif_body_lines)
                    elif elif_after:
                        elif_body = elif_after
                    else:
                        elif_body = ''
                        if i < len(lines):
                            elif_body = lines[i].strip()
                            i += 1

                    else_branches.append((elif_cond, elif_body))

                    # Get next line for else_branches loop
                    if pending_else:
                        next_line = pending_else
                        pending_else = None
                    elif i < len(lines):
                        next_line = lines[i].strip()
                    else:
                        next_line = ''
                    continue
                else:
                    break
            elif next_line.startswith('else'):
                # else branch (final)
                else_after = next_line[4:].strip()
                i += 1

                if else_after.startswith('{'):
                    else_body_lines = []
                    brace_count = 1

                    # Collect body with character-by-character brace counting
                    while i < len(lines) and brace_count > 0:
                        l = lines[i].strip()
                        found_close = False
                        for j, ch in enumerate(l):
                            if ch == '{':
                                brace_count += 1
                            elif ch == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    if j > 0:
                                        else_body_lines.append(l[:j])
                                    i += 1
                                    found_close = True
                                    break
                        if found_close:
                            break
                        else_body_lines.append(l)
                        i += 1
                    else_body = '\n'.join(else_body_lines)
                elif else_after:
                    else_body = else_after
                else:
                    else_body = ''
                    if i < len(lines):
                        else_body = lines[i].strip()
                        i += 1

                else_branches.append((None, else_body))
                break  # else is always last
            else:
                # Not an else/else if line, stop collecting
                break

        # Execute the if/else if/else chain
        cond_result = self.evaluate_condition(condition)
        if cond_result:
            if body:
                self.execute_body(body, context)
        else:
            # Try else if branches
            for elif_cond, elif_body in else_branches:
                if elif_cond is None:
                    # This is the else branch
                    if elif_body:
                        self.execute_body(elif_body, context)
                    break
                elif self.evaluate_condition(elif_cond):
                    if elif_body:
                        self.execute_body(elif_body, context)
                    break

        return i

    def execute_command(self, line: str, context: dict = None):
        """Execute a single command."""
        if not line or line.startswith('//'):
            return

        line = line.strip()
        if line.endswith(';'):
            line = line[:-1]

        # Handle assignment
        if '=' in line and not any(op in line for op in ['==', '!=', '<=', '>=']):
            parts = line.split('=', 1)
            var_name = parts[0].strip()
            value_str = parts[1].strip()

            if var_name.lower() == 'timeout':
                self._cmd_timeout(value_str, context)
                return

            value = self.evaluate_expression(value_str)
            self.set_variable(var_name, value)
            return

        # Handle increment/decrement
        if line.endswith('++'):
            var_name = line[:-2].strip()
            val = self.get_variable(var_name)
            try:
                self.set_variable(var_name, int(val) + 1)
            except:
                pass
            return
        if line.endswith('--'):
            var_name = line[:-2].strip()
            val = self.get_variable(var_name)
            try:
                self.set_variable(var_name, int(val) - 1)
            except:
                pass
            return

        # Parse command
        parts = line.split(None, 1)
        if not parts:
            return

        cmd = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ''

        # Command handlers
        if cmd == 'tokenize':
            self._cmd_tokenize(args_str, context)
        elif cmd == 'setstring':
            self._cmd_setstring(args_str, context)
        elif cmd == 'deletestring':
            self._cmd_deletestring(args_str, context)
        elif cmd == 'setcharprop':
            self._cmd_setcharprop(args_str, context)
        elif cmd == 'setplayerprop':
            self._cmd_setplayerprop(args_str, context)
        elif cmd == 'triggeraction':
            self._cmd_triggeraction(args_str, context)
        elif cmd == 'setshootparams':
            self._cmd_setshootparams(args_str, context)
        elif cmd == 'shoot':
            self._cmd_shoot(args_str, context)
        elif cmd == 'play':
            self._cmd_play(args_str, context)
        elif cmd == 'showimg' or cmd == 'showtext':
            self._cmd_showimg(args_str, context)
        elif cmd == 'hideimg':
            self._cmd_hideimg(args_str, context)
        elif cmd == 'hideimgs':
            self._cmd_hideimgs(args_str, context)
        elif cmd == 'sleep':
            self._cmd_sleep(args_str, context)
        elif cmd == 'setshape' or cmd == 'setshape2':
            pass  # Shape is parsed separately
        elif cmd == 'timereverywhere':
            pass  # Timer flag
        elif cmd == 'timeout':
            self._cmd_timeout(args_str, context)
        elif cmd == 'say':
            self._cmd_say(args_str, context)
        elif cmd == 'say2':
            self._cmd_say2(args_str, context)
        elif cmd == 'message':
            self._cmd_message(args_str, context)
        elif cmd == 'changeimgcolors' or cmd == 'changeimgzoom' or cmd == 'changeimgvis':
            pass  # Image modification
        elif cmd == 'disabledefmovement':
            self.default_movement_enabled = False
        elif cmd == 'enabledefmovement':
            self.default_movement_enabled = True
        elif cmd == 'freezeplayer':
            self._cmd_freezeplayer(args_str, context)

    def _cmd_tokenize(self, args: str, context: dict):
        """tokenize string(separator) - split string into tokens."""
        # Format: tokenize variable(separator) or tokenize #P1(-1)
        match = re.match(r'([^(]+)\(([^)]*)\)', args)
        if match:
            var_expr = match.group(1).strip()
            separator = match.group(2).strip()

            value = str(self.evaluate_expression(var_expr))

            if separator == '-1' or separator == '':
                # Comma separator
                self.tokens = [t.strip() for t in value.split(',') if t.strip()]
            else:
                self.tokens = [t.strip() for t in value.split(separator) if t.strip()]

    def _cmd_setstring(self, args: str, context: dict):
        """setstring name,value - set a string variable."""
        parts = args.split(',', 1)
        if len(parts) >= 1:
            name = parts[0].strip()
            value = self.evaluate_expression(parts[1].strip()) if len(parts) > 1 else ''
            self.variables[name] = value

    def _cmd_deletestring(self, args: str, context: dict):
        """deletestring name,index - delete item from string array."""
        parts = args.split(',')
        if len(parts) >= 2:
            name = parts[0].strip()
            try:
                idx = int(self.evaluate_expression(parts[1].strip()))
                value = self.get_variable(name)
                if isinstance(value, str):
                    items = [i.strip() for i in value.split(',')]
                    if 0 <= idx < len(items):
                        items.pop(idx)
                    self.set_variable(name, ','.join(items))
            except:
                pass

    def _cmd_setcharprop(self, args: str, context: dict):
        """setcharprop #Pn,value - set NPC char property and sync to server."""
        parts = args.split(',', 1)
        if len(parts) >= 1:
            prop = parts[0].strip()
            value_str = parts[1].strip() if len(parts) > 1 else ''

            # Handle GS1 string interpolation (concatenated expressions like #P1(-1)#e(...)"#a")
            value = self._evaluate_interpolated_string(value_str)

            # Extract property name (e.g., #P1 -> P1)
            if prop.startswith('#'):
                prop = prop[1:]

            self.npc_char_props[prop] = str(value)

            # Send to server using NPCPROP_GATTRIB
            # P1 -> GATTRIB1, P2 -> GATTRIB2, etc.
            if self.client and self.current_npc_id:
                self.client.send_npc_props(self.current_npc_id, prop, str(value))
                print(f"  [NPC PROP] Sent #{prop}={value} to NPC {self.current_npc_id}")

    def _evaluate_interpolated_string(self, s: str) -> str:
        """Evaluate a GS1 interpolated string with concatenated expressions."""
        result = []
        i = 0

        while i < len(s):
            if s[i] == '"':
                # Quoted string - find end quote and evaluate GS1 expressions inside
                j = i + 1
                while j < len(s) and s[j] != '"':
                    j += 1
                inner = s[i+1:j]
                # Recursively evaluate expressions in the quoted string
                result.append(self._evaluate_interpolated_string(inner))
                i = j + 1
            elif s[i:i+2] == '#P':
                # #Pn or #Pn(-1) - char prop
                match = re.match(r'#P(\d+)(\(-1\))?', s[i:])
                if match:
                    prop_num = match.group(1)
                    key = f'P{prop_num}'
                    result.append(self.npc_char_props.get(key, ''))
                    i += match.end()
                else:
                    result.append(s[i])
                    i += 1
            elif s[i:i+2] == '#e':
                # #e(start,count,sep) - conditional separator
                # If count > 0, output the separator, otherwise output nothing
                # The value after the #e() is processed separately
                if s[i+2:i+3] == '(':
                    # Parse exactly 3 comma-separated arguments
                    # The third arg (separator) might itself be a comma, so we stop after 2 commas
                    j = i + 3
                    args = []
                    current_arg = []
                    depth = 1
                    comma_count = 0

                    while j < len(s) and depth > 0:
                        if s[j] == '(':
                            depth += 1
                            current_arg.append(s[j])
                        elif s[j] == ')':
                            depth -= 1
                            if depth == 0:
                                args.append(''.join(current_arg))
                            else:
                                current_arg.append(s[j])
                        elif s[j] == ',' and depth == 1:
                            comma_count += 1
                            if comma_count <= 2:
                                args.append(''.join(current_arg))
                                current_arg = []
                            else:
                                # After 2 commas, remaining content is the separator
                                current_arg.append(s[j])
                        else:
                            current_arg.append(s[j])
                        j += 1

                    if len(args) >= 2:
                        count_expr = args[1]
                        separator = args[2] if len(args) > 2 else ''.join(current_arg).rstrip(')')

                        # Evaluate the count expression
                        count_raw = self._eval_paren_expr(count_expr)
                        try:
                            count = int(float(count_raw))
                        except:
                            count = 0

                        # If count > 0, output the separator
                        if count > 0:
                            result.append(separator)

                        # Continue parsing after the closing paren
                        i = j
                    else:
                        result.append('#e')
                        i += 2
                else:
                    result.append('#e')
                    i += 2
            elif s[i:i+2] == '#a':
                # Account name
                if self.client:
                    result.append(self.client.player.account or '')
                i += 2
            elif s[i:i+2] == '#c':
                # Chat message
                result.append(self.variables.get('player_chat', ''))
                i += 2
            elif s[i:i+3] == '#s(':
                # Server string #s(name)
                match = re.match(r'#s\(([^)]+)\)', s[i:])
                if match:
                    name = match.group(1)
                    result.append(self.server_strings.get(name, ''))
                    i += match.end()
                else:
                    result.append(s[i])
                    i += 1
            elif s[i] == '#':
                # Other # expression - try to find the end
                j = i + 1
                while j < len(s) and (s[j].isalnum() or s[j] in '(),-_'):
                    if s[j] == '(':
                        # Skip to matching paren
                        depth = 1
                        j += 1
                        while j < len(s) and depth > 0:
                            if s[j] == '(':
                                depth += 1
                            elif s[j] == ')':
                                depth -= 1
                            j += 1
                    else:
                        j += 1
                expr = s[i:j]
                result.append(str(self.evaluate_expression(expr)))
                i = j
            else:
                # Regular character or unrecognized - skip whitespace, stop at special chars
                if s[i].isspace():
                    i += 1
                else:
                    result.append(s[i])
                    i += 1

        return ''.join(result)

    def _eval_paren_expr(self, expr: str) -> Any:
        """Evaluate a parenthesized expression like !strequals(#P1(-1),)."""
        expr = expr.strip()

        # Handle parentheses wrapping
        if expr.startswith('(') and expr.endswith(')'):
            # Check if these parens are matching (not part of a function call)
            depth = 0
            matched = True
            for i, c in enumerate(expr):
                if c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                if depth == 0 and i < len(expr) - 1:
                    matched = False
                    break
            if matched:
                return self._eval_paren_expr(expr[1:-1])

        # Handle negation
        if expr.startswith('!'):
            inner = expr[1:]
            result = self._eval_paren_expr(inner)
            try:
                return 0 if result else 1
            except:
                return 0

        # Handle strequals
        if expr.startswith('strequals('):
            match = re.match(r'strequals\(([^,]*),([^)]*)\)', expr)
            if match:
                a = self._evaluate_interpolated_string(match.group(1).strip())
                b = self._evaluate_interpolated_string(match.group(2).strip())
                return 1 if a == b else 0

        return self.evaluate_expression(expr)

    def _cmd_setplayerprop(self, args: str, context: dict):
        """setplayerprop #prop,value - set player property."""
        parts = args.split(',', 1)
        if len(parts) >= 2:
            prop = parts[0].strip()
            value_str = parts[1].strip()

            # Check if this looks like a literal string (starts with : or contains non-variable chars)
            if value_str.startswith(':') or (not value_str.startswith('#') and
                                             not value_str.startswith('"') and
                                             ':' in value_str):
                value = value_str
            else:
                value = self.evaluate_expression(value_str)

            if prop == '#c':
                # Chat message - send as local level chat (shows above head)
                print(f"  [CHAT] {value}")
                if self.client:
                    self.client.send_level_chat(str(value))
                if self.on_setplayerprop:
                    self.on_setplayerprop('chat', str(value))
            elif self.on_setplayerprop:
                self.on_setplayerprop(prop, str(value))

    def _cmd_triggeraction(self, args: str, context: dict):
        """triggeraction x,y,action,params - trigger server action."""
        parts = [p.strip() for p in args.split(',')]
        if len(parts) >= 3:
            try:
                x = float(self.evaluate_expression(parts[0]))
                y = float(self.evaluate_expression(parts[1]))
            except:
                x, y = 0, 0

            action = ','.join(parts[2:])

            if self.on_triggeraction:
                self.on_triggeraction(x, y, action, self.current_npc_id)
            elif self.client:
                self.client.triggeraction(action, self.client.x, self.client.y, self.current_npc_id)

    def _cmd_setshootparams(self, args: str, context: dict):
        """setshootparams weapon,params... - set shoot parameters."""
        parts = [p.strip() for p in args.split(',')]
        if parts:
            self.variables['_shoot_weapon'] = parts[0]
            self.variables['_shoot_params'] = parts[1:] if len(parts) > 1 else []

    def _cmd_shoot(self, args: str, context: dict):
        """shoot params... - fire projectile."""
        params = [p.strip() for p in args.split(',')] if args else []
        weapon = self.variables.get('_shoot_weapon', 'default')

        print(f"  [SHOOT] {weapon} {params}")

        if self.on_shoot:
            self.on_shoot(weapon, params)

    def _cmd_play(self, args: str, context: dict):
        """play sound - play a sound file."""
        sound = args.strip()
        print(f"  [PLAY] {sound}")
        if self.on_play:
            self.on_play(sound)

    def _cmd_showimg(self, args: str, context: dict):
        """showimg id,image,x,y - show image."""
        parts = [p.strip() for p in args.split(',')]
        if len(parts) >= 2:
            try:
                img_id = int(self.evaluate_expression(parts[0]))
                image = parts[1]
                x = float(self.evaluate_expression(parts[2])) if len(parts) > 2 else 0
                y = float(self.evaluate_expression(parts[3])) if len(parts) > 3 else 0

                self.shown_images[img_id] = {'image': image, 'x': x, 'y': y}

                if self.on_showimg:
                    self.on_showimg(img_id, image, x, y)
            except:
                pass

    def _cmd_hideimg(self, args: str, context: dict):
        """hideimg id - hide image."""
        try:
            img_id = int(self.evaluate_expression(args.strip()))
            if img_id in self.shown_images:
                del self.shown_images[img_id]
            if self.on_hideimg:
                self.on_hideimg(img_id)
        except:
            pass

    def _cmd_hideimgs(self, args: str, context: dict):
        """hideimgs start,end - hide range of images."""
        parts = [p.strip() for p in args.split(',')]
        if len(parts) >= 2:
            try:
                start = int(self.evaluate_expression(parts[0]))
                end = int(self.evaluate_expression(parts[1]))
                for img_id in range(start, end):
                    if img_id in self.shown_images:
                        del self.shown_images[img_id]
                    if self.on_hideimg:
                        self.on_hideimg(img_id)
            except:
                pass

    def _cmd_sleep(self, args: str, context: dict):
        """sleep seconds - pause execution."""
        try:
            seconds = float(self.evaluate_expression(args.strip()))
            time.sleep(seconds)
        except:
            pass

    def _cmd_timeout(self, args: str, context: dict):
        """timeout = seconds - set timeout."""
        try:
            seconds = float(self.evaluate_expression(args.strip()))
            if self.current_script:
                self.script_timeouts[self.current_script] = time.time() + seconds
        except:
            pass

    def _cmd_say(self, args: str, context: dict):
        """say message - show chat bubble above NPC."""
        message = args.strip()
        print(f"  [SAY] NPC {self.current_npc_id}: {message}")
        if self.on_say:
            self.on_say(self.current_npc_id, message)

    def _cmd_say2(self, args: str, context: dict):
        """say2 message - show sign/dialogue box."""
        message = args.strip()
        print(f"  [SAY2/SIGN] {message}")
        if self.on_message:
            self.on_message(message)

    def _cmd_message(self, args: str, context: dict):
        """message text - show message."""
        print(f"  [MESSAGE] {args}")
        if self.on_message:
            self.on_message(args)

    def _cmd_freezeplayer(self, args: str, context: dict):
        """freezeplayer seconds - freeze player."""
        try:
            seconds = float(self.evaluate_expression(args.strip()))
            self.player_frozen = True
            self.freeze_until = time.time() + seconds
        except:
            pass

    def trigger_event(self, event: str, npc_id: int = 0, npc_x: float = 0, npc_y: float = 0, context: dict = None):
        """Trigger an event on scripts."""
        if context is None:
            context = {}

        self.current_npc_id = npc_id
        self.current_npc_x = npc_x
        self.current_npc_y = npc_y

        # Set event flag
        self.variables[f'_{event.lower()}'] = True

        for name, code in self.scripts.items():
            blocks = self.parse_blocks(code)
            for block in blocks:
                if event.lower() in block['condition'].lower():
                    self.current_script = name
                    self.execute_body(block['body'], context)
                    self.current_script = None

        # Clear event flag
        self.variables[f'_{event.lower()}'] = False

    def update(self):
        """Check for expired timeouts."""
        now = time.time()
        expired = []

        for script_name, expire_time in list(self.script_timeouts.items()):
            if now >= expire_time:
                expired.append(script_name)

        for script_name in expired:
            del self.script_timeouts[script_name]
            if script_name in self.scripts:
                code = self.scripts[script_name]
                blocks = self.parse_blocks(code)
                for block in blocks:
                    if 'timeout' in block['condition'].lower():
                        self.variables['_timeout'] = True
                        self.current_script = script_name
                        self.execute_body(block['body'], {})
                        self.current_script = None
                        self.variables['_timeout'] = False

        # Update freeze
        if self.player_frozen and time.time() >= self.freeze_until:
            self.player_frozen = False

    def is_movement_allowed(self) -> bool:
        """Check if player can move."""
        return self.default_movement_enabled and not self.player_frozen


def test_gs1():
    """Test GS1 interpreter with Bomber Arena queue script."""
    print("=== GS1 Interpreter Test ===\n")

    interp = GS1Interpreter()

    # Simulate player account
    class MockClient:
        def __init__(self):
            self.x = 25.0
            self.y = 19.0
            self.players = {}

        class player:
            account = "TestPlayer"
            direction = 0

        def triggeraction(self, action, x, y, npc_id):
            print(f"  [CLIENT] triggeraction: {action}")

        def say(self, msg):
            print(f"  [CLIENT] say: {msg}")

    interp.client = MockClient()

    # Load Bomber Arena queue script (simplified)
    script = '''if(playerenters) {
timereverywhere;
setshape2 14,1,{22,22,0,0,0,0,22,22,0,0,0,0,22,22};
this.on=0;
timeout = 0.5;
}
if(playertouchsme && playerdir == 0) {
triggeraction 0,0,gr.addweapon,-validation;
if(playerx < x+2) this.step = 1;
else if(playerx < x+8) this.step = 2;
else this.step = 3;
if(this.step==1)tokenize #P1(-1);
if(tokenscount<11) {
play sen_select.wav;
setplayerprop #c,:Added:;
setcharprop #P1,#P1(-1)#e(0,(!strequals(#P1(-1),)),,)"#a";
} else {
setplayerprop #c,:Full:;
}
timeout = 0.05;
}'''

    interp.load_script("queue_npc", script, npc_id=363, x=25.0, y=18.0)

    print("=== Trigger playerenters ===")
    interp.trigger_event("playerenters", npc_id=363, npc_x=25.0, npc_y=18.0)

    print("\n=== Trigger playertouchsme (direction 0) ===")
    interp.trigger_event("playertouchsme", npc_id=363, npc_x=25.0, npc_y=18.0)

    print(f"\nNPC char props: {interp.npc_char_props}")
    print(f"this.step: {interp.this_vars.get('this.step')}")

    # Trigger again to add second player
    print("\n=== Second touch ===")
    interp.client.player.account = "Player2"
    interp.trigger_event("playertouchsme", npc_id=363, npc_x=25.0, npc_y=18.0)

    print(f"\nNPC char props: {interp.npc_char_props}")


if __name__ == "__main__":
    test_gs1()
