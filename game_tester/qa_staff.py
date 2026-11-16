"""The staff account a private QA server provisions for the RC/NC coverage runs.

Kept apart from qa_server so the coverage harness can name the account without
importing the server manager (which `python -m game_tester.qa_server` runs).
"""

QA_STAFF_ACCOUNT = "qastaff"
