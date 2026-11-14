"""Regression tests for Android instrumentation result checking (no ADB needed)."""
import unittest

from android_emulator_smoke import check_instrumentation_result


SUCCESS = "\nTime: 3.41\n\nOK (2 tests)\n\nINSTRUMENTATION_CODE: -1\n"


class AndroidInstrumentationReportTests(unittest.TestCase):
    def test_exact_two_successful_tests(self):
        check_instrumentation_result(SUCCESS)

    def test_junit_report_with_windows_newlines(self):
        check_instrumentation_result(SUCCESS.replace("\n", "\r\n"))

    def test_one_or_three_tests_are_insufficient(self):
        for count in (0, 1, 3, 12):
            with self.subTest(count=count):
                with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
                    check_instrumentation_result(
                        SUCCESS.replace("OK (2 tests)", f"OK ({count} tests)")
                    )

    def test_reject_report_without_runner_success_code(self):
        for result_code in ("0", "1", "-2", ""):
            with self.subTest(result_code=result_code):
                with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
                    check_instrumentation_result(
                        SUCCESS.replace("INSTRUMENTATION_CODE: -1",
                                        "INSTRUMENTATION_CODE: " + result_code)
                    )

    def test_reject_failures_even_with_stale_success_text(self):
        for marker in ("FAILURES!!!", "INSTRUMENTATION_FAILED",
                       "INSTRUMENTATION_ABORTED"):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
                    check_instrumentation_result(SUCCESS + marker + "\n")

    def test_reject_embedded_success_fragment(self):
        with self.assertRaisesRegex(RuntimeError, "failed or skipped"):
            check_instrumentation_result(
                SUCCESS.replace("\nOK (2 tests)", "\nnot OK (2 tests)")
            )


if __name__ == "__main__":
    unittest.main()
