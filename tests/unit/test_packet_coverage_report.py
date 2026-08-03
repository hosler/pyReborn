from game_tester.packet_coverage import CoverageReport


def test_empty_server_rows_with_client_packets_report_zero_and_warning(capsys):
    report = CoverageReport(account="tester", client_sent={1: ["00"]})

    assert report.coverage_pct() == 0.0
    report.print_summary()

    assert "NO PACKETS: the session exercised nothing" in capsys.readouterr().out


def test_nonempty_server_rows_keep_existing_coverage_calculation():
    report = CoverageReport(
        account="tester",
        server_out={1: 1, 2: 1},
        client_stats={
            1: {"received": 1, "handled": 1, "errors": 0},
            2: {"received": 1, "handled": 0, "errors": 0},
        },
    )

    assert report.coverage_pct() == 50.0
