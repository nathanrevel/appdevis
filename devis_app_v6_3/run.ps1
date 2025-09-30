
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install flask flask_sqlalchemy
$env:FLASK_APP = "app.py"
flask run
