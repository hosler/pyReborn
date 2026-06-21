"""
TestReporter - Generate and display test results.

Supports console output, JSON, and HTML reports.
"""

import json
import time
import base64
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from .game_bot import Issue, ActionLog


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration: float
    details: str = ""
    issues: List[Issue] = None
    screenshot: Optional[bytes] = None

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


class TestReporter:
    """
    Generate and display test results.

    Usage:
        reporter = TestReporter()
        reporter.add_result("test_movement", True, 1.5, "Moved 10 tiles")
        reporter.add_issue("HIGH", "Position desync detected", {...})
        reporter.print_summary()
        reporter.save_json("report.json")
        reporter.save_html("report.html")
    """

    # ANSI color codes
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def __init__(self, name: str = "Game Tester"):
        self.name = name
        self.results: List[TestResult] = []
        self.issues: List[Issue] = []
        self.screenshots: Dict[str, bytes] = {}
        self.start_time = time.time()
        self.config: Dict[str, Any] = {}

    def set_config(self, **kwargs):
        """Set test configuration for report."""
        self.config.update(kwargs)

    def add_result(self, name: str, passed: bool, duration: float,
                   details: str = "", issues: List[Issue] = None,
                   screenshot: bytes = None):
        """Add a test result."""
        self.results.append(TestResult(
            name=name,
            passed=passed,
            duration=duration,
            details=details,
            issues=issues or [],
            screenshot=screenshot
        ))

        # Also track issues separately
        if issues:
            self.issues.extend(issues)

    def add_issue(self, severity: str, description: str,
                  context: Dict[str, Any] = None, category: str = "general",
                  screenshot: bytes = None):
        """Add a standalone issue."""
        issue = Issue(
            timestamp=time.time(),
            severity=severity,
            category=category,
            description=description,
            context=context or {},
            screenshot=screenshot
        )
        self.issues.append(issue)

    def add_screenshot(self, name: str, data: bytes):
        """Add a screenshot."""
        self.screenshots[name] = data

    # ========== Console Output ==========

    def print_header(self):
        """Print test header."""
        print(f"\n{'=' * 60}")
        print(f"  {self.BOLD}{self.name.upper()}{self.RESET}")
        print(f"{'=' * 60}")

        if self.config:
            for key, value in self.config.items():
                print(f"  {key}: {value}")
            print(f"{'=' * 60}")
        print()

    def print_result(self, result: TestResult):
        """Print a single test result."""
        if result.passed:
            status = f"{self.GREEN}[✓]{self.RESET}"
        else:
            status = f"{self.RED}[✗]{self.RESET}"

        name = result.name.ljust(35)
        duration = f"{result.duration:.1f}s".rjust(8)

        print(f"{status} {name} {duration}")

        if result.details:
            print(f"    {result.details}")

        for issue in result.issues:
            # Handle both Issue objects and plain strings
            if isinstance(issue, str):
                print(f"    {self.YELLOW}[INFO]{self.RESET} {issue}")
            else:
                color = self.RED if issue.severity == "HIGH" else self.YELLOW
                print(f"    {color}[{issue.severity}]{self.RESET} {issue.description}")

    def print_summary(self):
        """Print full test summary."""
        self.print_header()

        # Print results
        print(f"{self.BOLD}[TEST RESULTS]{self.RESET}")
        for result in self.results:
            self.print_result(result)

        # Summary stats
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)
        # Handle both Issue objects and strings
        warnings = sum(1 for i in self.issues if hasattr(i, 'severity') and i.severity == "WARN")

        print(f"\n{'=' * 60}")
        print(f"  {self.BOLD}SUMMARY{self.RESET}")
        print(f"{'=' * 60}")
        print(f"  {self.GREEN}Passed:{self.RESET}   {passed}/{total}")
        print(f"  {self.RED}Failed:{self.RESET}   {failed}/{total}")
        if warnings:
            print(f"  {self.YELLOW}Warnings:{self.RESET} {warnings}")

        # Pass rate
        if total > 0:
            rate = passed / total * 100
            color = self.GREEN if rate >= 80 else (self.YELLOW if rate >= 50 else self.RED)
            print(f"\n  Pass Rate: {color}{rate:.0f}%{self.RESET}")

        # Issues summary - handle both Issue objects and strings
        high_issues = [i for i in self.issues if hasattr(i, 'severity') and i.severity == "HIGH"]
        if high_issues:
            print(f"\n  {self.RED}High Priority Issues:{self.RESET}")
            for issue in high_issues[:5]:
                print(f"    - {issue.description}")

        # Duration
        duration = time.time() - self.start_time
        print(f"\n  Total Duration: {duration:.1f}s")
        print(f"{'=' * 60}\n")

    # ========== JSON Output ==========

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "name": self.name,
            "config": self.config,
            "start_time": self.start_time,
            "duration": time.time() - self.start_time,
            "summary": {
                "passed": sum(1 for r in self.results if r.passed),
                "failed": sum(1 for r in self.results if not r.passed),
                "total": len(self.results),
                "pass_rate": self.get_pass_rate()
            },
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "duration": r.duration,
                    "details": r.details,
                    "issues": [
                        {
                            "severity": i.severity,
                            "category": i.category,
                            "description": i.description,
                            "context": i.context
                        }
                        for i in r.issues
                    ]
                }
                for r in self.results
            ],
            "issues": [
                {
                    "timestamp": i.timestamp,
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                    "context": i.context
                }
                for i in self.issues
            ]
        }

    def save_json(self, filename: str):
        """Save report as JSON."""
        path = Path(filename)
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        print(f"  JSON report saved: {path}")

    # ========== HTML Output ==========

    def save_html(self, filename: str):
        """Save report as HTML with embedded screenshots."""
        path = Path(filename)

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        rate = self.get_pass_rate() * 100

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{self.name} Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .summary {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat {{ background: #f8f9fa; padding: 15px 25px; border-radius: 5px; text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; }}
        .stat-label {{ color: #666; font-size: 14px; }}
        .pass {{ color: #4CAF50; }}
        .fail {{ color: #f44336; }}
        .warn {{ color: #ff9800; }}
        .test {{ padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid; }}
        .test.passed {{ background: #e8f5e9; border-color: #4CAF50; }}
        .test.failed {{ background: #ffebee; border-color: #f44336; }}
        .test-name {{ font-weight: bold; }}
        .test-duration {{ color: #666; font-size: 14px; }}
        .issue {{ background: #fff3e0; padding: 10px; margin: 5px 0 5px 20px; border-radius: 3px; }}
        .issue.HIGH {{ background: #ffebee; border-left: 3px solid #f44336; }}
        .issue.MEDIUM {{ background: #fff3e0; border-left: 3px solid #ff9800; }}
        .issue.LOW {{ background: #e3f2fd; border-left: 3px solid #2196f3; }}
        .screenshot {{ max-width: 100%; margin: 10px 0; border: 1px solid #ddd; border-radius: 4px; }}
        .config {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        .config-item {{ margin: 5px 0; }}
        pre {{ background: #263238; color: #aed581; padding: 15px; border-radius: 5px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{self.name} Report</h1>

        <div class="config">
            <strong>Configuration:</strong>
            {''.join(f'<div class="config-item">{k}: {v}</div>' for k, v in self.config.items())}
            <div class="config-item">Duration: {time.time() - self.start_time:.1f}s</div>
        </div>

        <div class="summary">
            <div class="stat">
                <div class="stat-value pass">{passed}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="stat">
                <div class="stat-value fail">{total - passed}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat">
                <div class="stat-value" style="color: {'#4CAF50' if rate >= 80 else '#ff9800' if rate >= 50 else '#f44336'}">{rate:.0f}%</div>
                <div class="stat-label">Pass Rate</div>
            </div>
        </div>

        <h2>Test Results</h2>
"""

        for result in self.results:
            status = "passed" if result.passed else "failed"
            html += f"""
        <div class="test {status}">
            <span class="test-name">{result.name}</span>
            <span class="test-duration">{result.duration:.2f}s</span>
            {f'<div style="margin-top: 5px">{result.details}</div>' if result.details else ''}
"""
            for issue in result.issues:
                html += f"""
            <div class="issue {issue.severity}">
                <strong>[{issue.severity}]</strong> {issue.description}
            </div>
"""
            if result.screenshot:
                b64 = base64.b64encode(result.screenshot).decode('utf-8')
                html += f'<img class="screenshot" src="data:image/png;base64,{b64}" alt="Screenshot"/>'

            html += "</div>\n"

        # Issues section
        high_issues = [i for i in self.issues if i.severity == "HIGH"]
        if high_issues:
            html += """
        <h2>High Priority Issues</h2>
"""
            for issue in high_issues:
                html += f"""
        <div class="issue HIGH">
            <strong>[{issue.category}]</strong> {issue.description}
            {f'<pre>{json.dumps(issue.context, indent=2)}</pre>' if issue.context else ''}
        </div>
"""

        html += """
    </div>
</body>
</html>
"""

        with open(path, 'w') as f:
            f.write(html)
        print(f"  HTML report saved: {path}")

    # ========== Utilities ==========

    def get_pass_rate(self) -> float:
        """Get pass rate as float (0.0 - 1.0)."""
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    def has_failures(self) -> bool:
        """Check if any tests failed."""
        return any(not r.passed for r in self.results)

    def get_high_priority_issues(self) -> List[Issue]:
        """Get all HIGH severity issues."""
        return [i for i in self.issues if i.severity == "HIGH"]
