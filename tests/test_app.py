"""Dashboard backend regressions. Uses a temporary database and no external services."""
import pathlib, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app, db

class DashboardTests(unittest.TestCase):
    def test_output_containment(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d) / 'out'
            with patch.object(app, 'ALLOWED_FILE_ROOTS', return_value=[root.resolve()]):
                self.assertTrue(app.allowed_file((root/'resume.pdf').resolve()))
                self.assertFalse(app.allowed_file((root.parent/'out-private'/'secret').resolve()))
                self.assertFalse(app.allowed_file((root/'..'/'secret').resolve()))

    def test_undo_returns_prepared_job_to_review(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(db, 'DB_PATH', pathlib.Path(d)/'jobs.db'):
                c = db.conn()
                c.execute("INSERT INTO jobs(id,status,resume_pdf) VALUES ('test','approved','resume.pdf')")
                c.commit()
                with patch.object(db, 'conn', return_value=c):
                    self.assertTrue(app.job_action('test', {'action':'reopen'})['ok'])
                row = c.execute("SELECT status,resume_pdf FROM jobs WHERE id='test'").fetchone()
                self.assertEqual(tuple(row), ('ready','resume.pdf'))
                c.close()

    def test_cross_site_posts_rejected(self):
        handler = object.__new__(app.H)
        handler.headers = {'Host':'localhost:8766','Origin':'https://evil.example','Content-Type':'application/json'}
        self.assertFalse(handler._same_origin())
        handler.headers['Origin'] = 'http://localhost:8766'
        self.assertTrue(handler._same_origin())
        handler.headers['Content-Type'] = 'text/plain'
        self.assertFalse(handler._same_origin())

if __name__ == '__main__': unittest.main()
