import click

from hrms.setup import after_install as setup


def after_install():
	try:
		print("Setting up F-Payroll...")
		setup()

		click.secho("Thank you for installing F-Payroll!", fg="green")

	except Exception as e:
		BUG_REPORT_URL = "https://github.com/frappe/hrms/issues/new"
		click.secho(
			"Installation for F-Payroll app failed due to an error."
			" Please try re-installing the app or"
			f" report the issue on {BUG_REPORT_URL} if not resolved.",
			fg="bright_red",
		)
		raise e
