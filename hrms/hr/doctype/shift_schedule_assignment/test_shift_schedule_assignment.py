# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

<<<<<<< HEAD
# import frappe
from frappe.tests.utils import FrappeTestCase
=======
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, getdate

from erpnext.setup.doctype.employee.test_employee import make_employee

from hrms.hr.doctype.shift_schedule.shift_schedule import get_or_insert_shift_schedule
from hrms.hr.doctype.shift_type.test_shift_type import setup_shift_type
>>>>>>> c5061aa9 (test: validate existing shift assignments before saving shift schedule assignment)

# On FrappeTestCase, the doctype test records and all
# link-field test record depdendencies are recursively loaded
# Use these module variables to add/remove to/from that list


<<<<<<< HEAD
class TestShiftScheduleAssignment(FrappeTestCase):
	"""
	Integration tests for ShiftScheduleAssignment.
	Use this class for testing interactions between multiple components.
	"""
=======
class TestShiftScheduleAssignment(IntegrationTestCase):
	def setUp(self):
		frappe.db.delete("Shift Type", "Shift Schedule" "Shift Schedule Assignment")
>>>>>>> c5061aa9 (test: validate existing shift assignments before saving shift schedule assignment)

		self.employee = make_employee("test@scheduleassignment.com", company="_Test Company")
		self.shift_type = setup_shift_type(
			shift_type="Test Schedule Assignment", start_time="08:00:00", end_time="12:00:00"
		)
		self.shift_schedule = get_or_insert_shift_schedule(self.shift_type.name, "Every Week", ["Monday"])

	def tearDown(self):
		frappe.db.rollback()

	def test_existing_shift_assignment_validation(self):
		shift_schedule_assignment = frappe.get_doc(
			{
				"doctype": "Shift Schedule Assignment",
				"employee": self.employee,
				"company": "_Test Company",
				"shift_schedule": self.shift_schedule,
				"shift_status": "Active",
				"create_shifts_after": add_days(getdate(), -10),
			}
		).insert()
		create_shifts_after = shift_schedule_assignment.create_shifts_after

		shift_schedule_assignment.create_shifts(
			add_days(create_shifts_after, 1), add_days(create_shifts_after, 15)
		)

		shift_schedule_assignment.reload()
		shift_schedule_assignment.create_shifts_after = getdate()

		self.assertRaises(frappe.ValidationError, shift_schedule_assignment.save)
		shift_schedule_assignment.reload()
		shift_schedule_assignment.create_shifts_after = add_days(getdate(), 6)

		shift_schedule_assignment.save()
		self.assertEqual(shift_schedule_assignment.create_shifts_after, add_days(getdate(), 6))
