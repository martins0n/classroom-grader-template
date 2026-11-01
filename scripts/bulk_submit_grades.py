#!/usr/bin/env python3
"""
Bulk submit grades to Google Classroom from aggregated CSV file.

This script reads a CSV file containing student grades and submits them all
to Google Classroom via the API. You authenticate once, and it handles all students.
"""

import argparse
import csv
import sys
from pathlib import Path
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.classroom_client import ClassroomClient


def load_assignment_config(assignment_id: str) -> dict:
    """
    Load assignment configuration to get course_id and coursework_id.

    Args:
        assignment_id: Assignment identifier

    Returns:
        Dictionary with course_id, coursework_id, max_points
    """
    coursework_id_env = f"ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_COURSEWORK_ID"
    course_id_env = f"ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_COURSE_ID"
    max_points_env = f"ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_MAX_POINTS"

    if os.getenv(coursework_id_env) and os.getenv(course_id_env):
        return {
            'course_id': os.getenv(course_id_env),
            'coursework_id': os.getenv(coursework_id_env),
            'max_points': float(os.getenv(max_points_env, '100'))
        }

    return {}


def bulk_submit_grades(csv_file: str, dry_run: bool = False):
    """
    Submit all grades from CSV file to Google Classroom.

    Args:
        csv_file: Path to CSV file with grades
        dry_run: If True, don't actually submit grades (for testing)
    """
    csv_path = Path(csv_file)

    if not csv_path.exists():
        print(f"❌ Error: CSV file not found: {csv_file}")
        return False

    # Extract assignment ID from filename (grades_{assignment_id}.csv)
    filename = csv_path.stem
    if not filename.startswith('grades_'):
        print("❌ Error: CSV filename must be in format 'grades_{assignment_id}.csv'")
        print(f"   Got: {csv_path.name}")
        return False

    assignment_id = filename[7:]  # Remove 'grades_' prefix
    print(f"📚 Assignment: {assignment_id}")

    # Load assignment configuration
    assignment_config = load_assignment_config(assignment_id)

    if not assignment_config:
        print(f"\n❌ Error: No configuration found for assignment '{assignment_id}'")
        print("\nTo configure, set environment variables:")
        print(f"  ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_COURSE_ID=<course_id>")
        print(f"  ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_COURSEWORK_ID=<coursework_id>")
        print(f"  ASSIGNMENT_{assignment_id.upper().replace('-', '_')}_MAX_POINTS=100")
        return False

    course_id = assignment_config.get('course_id')
    coursework_id = assignment_config.get('coursework_id')
    max_points = assignment_config.get('max_points', 100)

    if not course_id or not coursework_id:
        print("❌ Error: Missing course_id or coursework_id in configuration")
        return False

    print(f"📖 Course ID: {course_id}")
    print(f"📝 Coursework ID: {coursework_id}")
    print(f"💯 Max Points: {max_points}")

    # Read CSV file
    grades = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            grades.append({
                'email': row['Student Email'],
                'grade': float(row['Grade']),
                'max_points': float(row.get('Max Points', max_points))
            })

    print(f"\n📊 Found {len(grades)} students in CSV")

    if dry_run:
        print("\n🧪 DRY RUN MODE - No grades will be submitted")
        for i, grade_entry in enumerate(grades, 1):
            print(f"   {i}. {grade_entry['email']}: {grade_entry['grade']}/{grade_entry['max_points']}")
        return True

    # Initialize Google Classroom client
    print("\n🔐 Authenticating with Google Classroom...")
    try:
        client = ClassroomClient()
        print("✓ Authentication successful")
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        print("\nMake sure you have:")
        print("1. Created credentials.json (see README.md)")
        print("2. Run authentication at least once locally")
        print("3. Set up token.json with required scopes")
        return False

    # Submit grades
    print("\n📤 Submitting grades to Google Classroom...")
    print("=" * 60)

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for i, grade_entry in enumerate(grades, 1):
        email = grade_entry['email']
        grade = grade_entry['grade']
        points = grade_entry['max_points']

        print(f"\n[{i}/{len(grades)}] {email}: {grade}/{points}")

        try:
            # Find student's submission
            submission_id = client.find_submission_for_student(
                course_id, coursework_id, email
            )

            if not submission_id:
                print("   ⚠️  No submission found - skipping")
                skipped_count += 1
                continue

            # Submit grade as draft
            success = client.submit_grade(
                course_id=course_id,
                coursework_id=coursework_id,
                submission_id=submission_id,
                grade=grade,
                max_points=points
            )

            if success:
                print("   ✓ Grade submitted successfully")
                success_count += 1
            else:
                print("   ✗ Submission failed")
                failed_count += 1

        except Exception as e:
            print(f"   ✗ Error: {e}")
            failed_count += 1

    # Summary
    print("\n" + "=" * 60)
    print("📊 SUBMISSION SUMMARY")
    print("=" * 60)
    print(f"✅ Successful: {success_count}")
    print(f"⚠️  Skipped (no submission): {skipped_count}")
    print(f"❌ Failed: {failed_count}")
    print(f"📝 Total: {len(grades)}")
    print("=" * 60)

    if success_count > 0:
        print("\n✨ Grades submitted as DRAFTS - review and approve them in Google Classroom!")

    return failed_count == 0


def main():
    parser = argparse.ArgumentParser(
        description="Bulk submit grades to Google Classroom from CSV"
    )
    parser.add_argument(
        'csv_file',
        help='Path to CSV file with grades (e.g., reports/aggregated/grades_homework-2.csv)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview what would be submitted without actually submitting'
    )

    args = parser.parse_args()

    try:
        success = bulk_submit_grades(args.csv_file, args.dry_run)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
