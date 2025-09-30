
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'change-me'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///devis.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Company info segmented
COMPANY = {
    "brand": "Alltricks Pro",
    "legal_name": "AVANIS SAS - Alltricks",
    "addr_line1": "5 Avenue Isaac Newton",
    "addr_postcode_city": "78180 Montigny-le-Bretonneux",
    "addr_country": "France",
    "hq_line1": "7 rue de la Fosse aux Canes",
    "hq_postcode_city": "28200 Châteaudun",
    "hq_country": "France",
    "phone": "Tél. : +33 (0)1 30 48 90 07",
    "email": "factures@alltricks.com",
    "tva_intra": "TVA Intracommunautaire FR 23 484 395 629",
    "capital": "SAS au capital social de 166 054€",
    "siren": "RCS CHARTRES 484 395 629",
    "rib_title": "Titulaire du compte : AVANIS",
    "rib": "RIB : 30004 02552 00011101451 07",
    "iban": "IBAN : FR76 3000 4025 5200 0111 0145 107",
    "bic": "BIC : BNPAFRPPIFO",
}

LEGAL_FOOTER = (
    "En cas de non-paiement à compter du 1er jour suivant la date d’échéance, "
    "des pénalités seront applicables à hauteur de 3 fois le taux légal en vigueur. "
    "Indemnité forfaitaire pour frais de recouvrement en cas de retard de paiement : 40€. "
    "Nos conditions de vente ne prévoient pas d'escompte pour paiement anticipé."
)

db = SQLAlchemy(app)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(120))
    company_abbr = db.Column(db.String(20))
    contact_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(60))
    address = db.Column(db.Text)
    city = db.Column(db.String(120))
    zip_code = db.Column(db.String(20))
    country = db.Column(db.String(80), default='France')
    quotes = db.relationship('Quote', backref='client', lazy=True)

class Quote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='Brouillon')
    title = db.Column(db.String(160), default='Devis')
    notes = db.Column(db.Text)
    issued_by = db.Column(db.String(120))
    attention_to = db.Column(db.String(120))
    valid_until = db.Column(db.Date)
    reference = db.Column(db.String(50), unique=True)
    year = db.Column(db.Integer)
    seq = db.Column(db.Integer)
    ref_locked = db.Column(db.Boolean, default=False)
    subtotal_ht = db.Column(db.Numeric(12,2), default=0)
    total_tva = db.Column(db.Numeric(12,2), default=0)
    total_ttc = db.Column(db.Numeric(12,2), default=0)
    items = db.relationship('QuoteItem', backref='quote', cascade="all, delete-orphan")

class QuoteItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quote_id = db.Column(db.Integer, db.ForeignKey('quote.id'), nullable=False)
    ref = db.Column(db.String(60))
    description = db.Column(db.String(240), nullable=False)
    quantity = db.Column(db.Numeric(10,2), default=1)
    unit_price = db.Column(db.Numeric(12,2), default=0)
    vat_rate = db.Column(db.Numeric(5,2), default=20)
    line_total_ht = db.Column(db.Numeric(12,2), default=0)
    line_total_tva = db.Column(db.Numeric(12,2), default=0)
    line_total_ttc = db.Column(db.Numeric(12,2), default=0)

with app.app_context():
    if not os.path.exists('devis.db'):
        db.create_all()

def to_decimal(val, default='0'):
    try:
        return Decimal(str(val).replace(',', '.'))
    except Exception:
        return Decimal(default)

def recompute_totals(quote: 'Quote'):
    subtotal = Decimal('0')
    total_tva = Decimal('0')
    for it in quote.items:
        qty = to_decimal(it.quantity, '0')
        pu = to_decimal(it.unit_price, '0')
        vat = to_decimal(it.vat_rate, '0')/Decimal('100')
        line_ht = (qty * pu).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        line_tva = (line_ht * vat).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        line_ttc = (line_ht + line_tva).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        it.line_total_ht = line_ht
        it.line_total_tva = line_tva
        it.line_total_ttc = line_ttc
        subtotal += line_ht
        total_tva += line_tva
    quote.subtotal_ht = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    quote.total_tva = total_tva.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    quote.total_ttc = (subtotal + total_tva).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def default_abbr(company: str) -> str:
    if not company:
        return 'XXX'
    clean = ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in company)
    words = [w for w in clean.split() if w]
    if len(words) == 1:
        return words[0][:3].upper()
    if len(words) == 2:
        return (words[0][:2] + words[1][:1]).upper()
    abbr = ''.join(w[0] for w in words).upper()
    return abbr[:6] if abbr else 'XXX'

def generate_reference(client_abbr: str):
    year = datetime.utcnow().year
    abbr = (client_abbr or '').strip().upper() or 'XXX'
    last = Quote.query.filter_by(year=year).filter(Quote.reference.like(f"{year}{abbr}%")).order_by(Quote.seq.desc()).first()
    next_seq = (last.seq + 1) if last and last.seq else 1
    return f"{year}{abbr}{next_seq:03d}", year, next_seq

from flask import render_template

@app.route('/')
def dashboard():
    last_quotes = Quote.query.order_by(Quote.created_at.desc()).limit(10).all()
    stats = {
        'count_clients': Client.query.count(),
        'count_quotes': Quote.query.count(),
        'count_draft': Quote.query.filter_by(status='Brouillon').count(),
        'count_sent': Quote.query.filter_by(status='Envoyé').count(),
        'count_accepted': Quote.query.filter_by(status='Accepté').count(),
        'count_refused': Quote.query.filter_by(status='Refusé').count(),
    }
    return render_template('dashboard.html', last_quotes=last_quotes, stats=stats)

@app.route('/clients')
def clients_list():
    q = request.args.get('q', '').strip()
    query = Client.query
    if q:
        like = f"%{q}%"
        query = query.filter((Client.company.ilike(like)) | (Client.contact_name.ilike(like)) | (Client.email.ilike(like)))
    clients = query.order_by(Client.company.asc(), Client.contact_name.asc()).all()
    return render_template('clients_list.html', clients=clients, q=q)

@app.route('/clients/new', methods=['GET','POST'])
@app.route('/clients/<int:client_id>/edit', methods=['GET','POST'])
def clients_form(client_id=None):
    client = Client.query.get(client_id) if client_id else Client()
    if request.method == 'POST':
        client.company = request.form.get('company') or None
        client.company_abbr = request.form.get('company_abbr') or client.company_abbr
        client.contact_name = request.form.get('contact_name') or ''
        client.email = request.form.get('email') or None
        client.phone = request.form.get('phone') or None
        client.address = request.form.get('address') or None
        client.city = request.form.get('city') or None
        client.zip_code = request.form.get('zip_code') or None
        client.country = request.form.get('country') or 'France'
        db.session.add(client)
        db.session.commit()
        flash('Client enregistré', 'success')
        return redirect(url_for('clients_list'))
    return render_template('clients_form.html', client=client)

@app.route('/clients/<int:client_id>/delete', methods=['POST'])
def clients_delete(client_id):
    client = Client.query.get_or_404(client_id)
    db.session.delete(client)
    db.session.commit()
    flash('Client supprimé', 'info')
    return redirect(url_for('clients_list'))

@app.route('/quotes')
def quotes_list():
    status = request.args.get('status')
    client_id = request.args.get('client_id', type=int)
    query = Quote.query
    if status:
        query = query.filter_by(status=status)
    if client_id:
        query = query.filter_by(client_id=client_id)
    quotes = query.order_by(Quote.created_at.desc()).all()
    clients = Client.query.order_by(Client.company.asc()).all()
    return render_template('quotes_list.html', quotes=quotes, clients=clients, status=status, client_id=client_id)

@app.route('/quotes/new', methods=['GET','POST'])
@app.route('/quotes/<int:quote_id>/edit', methods=['GET','POST'])
def quotes_form(quote_id=None):
    quote = Quote.query.get(quote_id) if quote_id else Quote()
    clients = Client.query.order_by(Client.company.asc(), Client.contact_name.asc()).all()

    if request.method == 'POST':
        quote.client_id = int(request.form.get('client_id'))
        quote.title = request.form.get('title') or 'Devis'
        quote.status = request.form.get('status') or 'Brouillon'
        quote.notes = request.form.get('notes') or None
        quote.issued_by = request.form.get('issued_by') or None
        quote.attention_to = request.form.get('attention_to') or None

        valid_until_raw = request.form.get('valid_until')
        if valid_until_raw:
            try:
                quote.valid_until = datetime.fromisoformat(valid_until_raw).date()
            except Exception:
                quote.valid_until = (datetime.utcnow() + timedelta(days=30)).date()
        else:
            quote.valid_until = (datetime.utcnow() + timedelta(days=30)).date()

        if quote.id:
            quote.items.clear()

        rows = int(request.form.get('rows', 0))
        for i in range(1, rows+1):
            ref = request.form.get(f'ref_{i}') or None
            desc = request.form.get(f'desc_{i}')
            qty = to_decimal(request.form.get(f'qty_{i}') or '1')
            pu = to_decimal(request.form.get(f'pu_{i}') or '0')
            vat = to_decimal(request.form.get(f'vat_{i}') or '20')
            if desc and qty > 0:
                item = QuoteItem(ref=ref, description=desc, quantity=qty, unit_price=pu, vat_rate=vat)
                quote.items.append(item)
        recompute_totals(quote)

        client = Client.query.get(quote.client_id)
        if client and not client.company_abbr:
            client.company_abbr = (client.company or client.contact_name)[:3].upper()
            db.session.add(client)
        abbr = (client.company_abbr or (client.company or client.contact_name)[:3].upper()) if client else 'XXX'
        if not quote.reference:
            ref, year, seq = generate_reference(abbr)
            quote.reference, quote.year, quote.seq = ref, year, seq

        db.session.add(quote)
        db.session.commit()
        flash('Devis enregistré', 'success')
        return redirect(url_for('quotes_list'))
    return render_template('quotes_form.html', quote=quote, clients=clients)

@app.route('/quotes/<int:quote_id>')
def quote_view(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    return render_template('quote_view.html', quote=quote, COMPANY=COMPANY, LEGAL_FOOTER=LEGAL_FOOTER)

@app.route('/quotes/<int:quote_id>/status', methods=['POST'])
def quote_status(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    new_status = request.form.get('status')
    if new_status in ['Brouillon','Envoyé','Accepté','Refusé']:
        quote.status = new_status
        db.session.commit()
        flash('Statut mis à jour', 'success')
    return redirect(url_for('quotes_list'))

@app.route('/quotes/<int:quote_id>/lock', methods=['POST'])
def quote_lock(quote_id):
    quote = Quote.query.get_or_404(quote_id)
    quote.ref_locked = True
    db.session.commit()
    flash('Référence verrouillée', 'success')
    return redirect(url_for('quote_view', quote_id=quote.id))

if __name__ == '__main__':
    app.run(debug=True)
