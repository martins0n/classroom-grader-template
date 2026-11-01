"""
Google Classroom API client for downloading student submissions.
"""
import os
from typing import List, Dict, Optional
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import logging

from .naming import safe_filename, student_id_from_email

logger = logging.getLogger(__name__)

# GitHub rejects larger blobs anyway; stop before holding a huge attachment in memory.
MAX_ATTACHMENT_BYTES = 95 * 1024 * 1024

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.students.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.students.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.me.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.students',  # Required to submit grades
    'https://www.googleapis.com/auth/classroom.rosters.readonly',  # Required to get student emails
    'https://www.googleapis.com/auth/classroom.profile.emails',  # Required to access email addresses
    'https://www.googleapis.com/auth/drive.readonly'
]


class ClassroomClient:
    """Client for interacting with Google Classroom API."""

    def __init__(self, credentials_path: str = 'credentials.json', token_path: str = 'token.json'):
        """
        Initialize the Classroom client.

        Args:
            credentials_path: Path to the OAuth credentials JSON file
            token_path: Path to store the access token
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.drive_service = None
        self._authenticate()

    def _authenticate(self):
        """Authenticate with Google. Interactive login happens only in scripts/setup_course.py."""
        creds = None
        in_ci = bool(os.getenv('CI') or os.getenv('GITHUB_ACTIONS'))

        if os.path.exists(self.token_path):
            # JSON on purpose: unpickling a token file would execute whatever it contains.
            creds = Credentials.from_authorized_user_file(self.token_path)
            missing_scopes = set(SCOPES) - set(creds.scopes or [])
            if missing_scopes:
                if in_ci:
                    raise RuntimeError(
                        f"Token is missing required scopes: {sorted(missing_scopes)}. "
                        "Run scripts/setup_course.py again to refresh GOOGLE_TOKEN."
                    )
                logger.warning("Token is missing scopes; logging in again")
                creds = None

        if creds and not creds.valid and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired credentials")
            creds.refresh(Request())

        if not creds or not creds.valid:
            if in_ci:
                raise RuntimeError(
                    "No usable Google token. Run scripts/setup_course.py again to refresh "
                    "the GOOGLE_TOKEN secret."
                )
            if not os.path.exists(self.credentials_path):
                raise FileNotFoundError(
                    f"Credentials file not found at {self.credentials_path}. See README.md."
                )
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
            os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'  # tolerate reordered scopes
            try:
                creds = flow.run_local_server(port=0)
            finally:
                os.environ.pop('OAUTHLIB_RELAX_TOKEN_SCOPE', None)
            fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as token:
                token.write(creds.to_json())

        self.service = build('classroom', 'v1', credentials=creds)
        self.drive_service = build('drive', 'v3', credentials=creds)
        logger.info("Successfully authenticated with Google Classroom API")

    def list_courses(self) -> List[Dict]:
        """List all courses accessible to the authenticated user."""
        results = self.service.courses().list(pageSize=100).execute()
        courses = results.get('courses', [])
        return courses

    def list_course_work(self, course_id: str) -> List[Dict]:
        """
        List all coursework for a given course.

        Args:
            course_id: The ID of the course

        Returns:
            List of coursework items
        """
        coursework = []
        page_token = None
        while True:
            results = self.service.courses().courseWork().list(
                courseId=course_id,
                pageToken=page_token
            ).execute()
            coursework.extend(results.get('courseWork', []))
            page_token = results.get('nextPageToken')
            if not page_token:
                return coursework

    def list_students(self, course_id: str) -> List[Dict]:
        """
        List all students enrolled in a given course.

        Args:
            course_id: The ID of the course

        Returns:
            List of student objects with profile information
        """
        students = []
        page_token = None

        while True:
            results = self.service.courses().students().list(
                courseId=course_id,
                pageToken=page_token
            ).execute()

            students.extend(results.get('students', []))
            page_token = results.get('nextPageToken')

            if not page_token:
                break

        return students

    def get_submissions(self, course_id: str, coursework_id: str) -> List[Dict]:
        """
        Get all student submissions for a specific assignment.

        Args:
            course_id: The ID of the course
            coursework_id: The ID of the coursework/assignment

        Returns:
            List of submissions
        """
        submissions = []
        page_token = None

        while True:
            results = self.service.courses().courseWork().studentSubmissions().list(
                courseId=course_id,
                courseWorkId=coursework_id,
                pageToken=page_token
            ).execute()

            submissions.extend(results.get('studentSubmissions', []))
            page_token = results.get('nextPageToken')

            if not page_token:
                break

        return submissions

    def download_attachment(self, attachment: Dict, output_dir: Path) -> Optional[Path]:
        """
        Download a submission attachment.

        The title is chosen by the student and Drive titles may contain slashes, so it is
        reduced to a single file name before it touches the file system.

        Args:
            attachment: Attachment dictionary from submission
            output_dir: Directory to save the file

        Returns:
            Path to the downloaded file, or None if download failed
        """
        drive_file = attachment.get('driveFile')
        if not drive_file:
            logger.warning("Attachment type not supported: %s", sorted(attachment))
            return None

        name = safe_filename(drive_file.get('title'))
        output_dir = Path(output_dir).resolve()
        output_path = output_dir / name
        if output_path.parent != output_dir:
            logger.error("Rejected attachment with unsafe name")
            return None

        try:
            request = self.drive_service.files().get_media(fileId=drive_file['id'])
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
                if buffer.tell() > MAX_ATTACHMENT_BYTES:
                    logger.warning("Skipping attachment over the %d byte limit", MAX_ATTACHMENT_BYTES)
                    return None
            output_path.write_bytes(buffer.getvalue())
            logger.info("Downloaded attachment: %s", name)
            return output_path
        except Exception as e:
            # Typically a native Google Doc, which has no downloadable bytes.
            logger.warning("Could not download attachment %s: %s", name, e)
            return None

    def get_student_info(self, course_id: str, user_id: str) -> Dict:
        """
        Get student information.

        Args:
            course_id: The ID of the course
            user_id: The ID of the student

        Returns:
            Student information dictionary with email
        """
        try:
            student = self.service.courses().students().get(
                courseId=course_id,
                userId=user_id
            ).execute()
            return student
        except Exception as e:
            logger.error(f"Error getting student info: {e}")
            return {}

    def get_student_email(self, course_id: str, user_id: str) -> str:
        """
        Get student email address.

        Args:
            course_id: The ID of the course
            user_id: The ID of the student

        Returns:
            Student email address or user_id if email not available
        """
        try:
            student = self.get_student_info(course_id, user_id)
            profile = student.get('profile', {})
            email = profile.get('emailAddress', '')

            if email:
                return student_id_from_email(email)
            else:
                logger.warning(f"No email found for student {user_id}, using ID")
                return user_id
        except Exception as e:
            logger.error(f"Error getting student email: {e}")
            return user_id

    def submit_grade(
        self,
        course_id: str,
        coursework_id: str,
        submission_id: str,
        grade: float,
        max_points: Optional[float] = None
    ) -> bool:
        """
        Submit a draft grade for a student submission.

        Note: This submits a draft grade that must be approved by the teacher.
        The grade will not be final until the teacher reviews and approves it.

        Args:
            course_id: The ID of the course
            coursework_id: The ID of the coursework/assignment
            submission_id: The ID of the submission
            grade: The grade to assign (must be <= max_points)
            max_points: Maximum points for the assignment (optional, for validation)

        Returns:
            True if grade was submitted successfully, False otherwise
        """
        try:
            # Validate grade
            if max_points is not None and grade > max_points:
                logger.warning(
                    f"Grade {grade} exceeds max points {max_points}, capping at max"
                )
                grade = max_points

            # Prepare the update body
            body = {
                'draftGrade': grade
            }

            # Update the submission with draft grade
            result = self.service.courses().courseWork().studentSubmissions().patch(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=submission_id,
                updateMask='draftGrade',
                body=body
            ).execute()

            logger.info(
                f"Submitted draft grade {grade} for submission {submission_id} "
                f"(course: {course_id}, coursework: {coursework_id})"
            )
            return True

        except Exception as e:
            logger.error(f"Error submitting grade: {e}")
            return False

    def find_submission_for_student(
        self,
        course_id: str,
        coursework_id: str,
        student_email: str
    ) -> Optional[str]:
        """
        Find a submission ID for a specific student by email.

        Args:
            course_id: The ID of the course
            coursework_id: The ID of the coursework/assignment
            student_email: The student's email address

        Returns:
            Submission ID if found, None otherwise
        """
        try:
            submissions = self.get_submissions(course_id, coursework_id)

            for submission in submissions:
                user_id = submission.get('userId')
                student_info = self.get_student_info(course_id, user_id)
                profile = student_info.get('profile', {})
                email = profile.get('emailAddress', '')

                if email.lower() == student_email.lower():
                    return submission.get('id')

            logger.warning(
                f"No submission found for student {student_email} "
                f"in course {course_id}, coursework {coursework_id}"
            )
            return None

        except Exception as e:
            logger.error(f"Error finding submission: {e}")
            return None
