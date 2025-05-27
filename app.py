# app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime, timedelta
import json, pytz, os, re, uuid
from matrixCalculator import compute_matrix
from request_queue import RequestQueue
import hashlib # <--- ADD THIS IMPORT

app = Flask(__name__)
app.secret_key = "super_secret_key"

# RESULT_CACHE is no longer directly used by app.py for storage or popping.
# The RequestQueue's internal 'results' dictionary will serve as the primary cache.
# Keeping it here for context if other parts of the app rely on its existence,
# but its direct manipulation (e.g., .pop()) will be removed.
# RESULT_CACHE = {} # You can remove this line if it's not used elsewhere

with open('config.json', 'r', encoding='utf-8') as config_file:
    CONFIG = json.load(config_file)

with open('static/js/script.js', 'r', encoding='utf-8') as js_file:
    SCRIPT_JS_CONTENT = js_file.read()
with open('static/css/styles.css', 'r', encoding='utf-8') as css_file:
    STYLES_CSS_CONTENT = css_file.read()

def configure_request_queue():
    max_concurrent = CONFIG.get("queue_max_concurrent", 1)
    cooldown_period = CONFIG.get("queue_cooldown_period", 3)
    batch_cleanup_threshold = CONFIG.get("queue_batch_cleanup_threshold", 10)
    cleanup_interval = CONFIG.get("queue_cleanup_interval", 30)
    heartbeat_timeout = CONFIG.get("queue_heartbeat_timeout", 90)

    return RequestQueue(
        max_concurrent=max_concurrent,
        cooldown_period=cooldown_period,
        batch_cleanup_threshold=batch_cleanup_threshold,
        cleanup_interval=cleanup_interval,
        heartbeat_timeout=heartbeat_timeout
    )

request_queue = configure_request_queue()

with open('trains_en.json', 'r') as f:
    trains_data = json.load(f)
    trains = trains_data['trains']

def check_maintenance():
    if CONFIG.get("is_maintenance", 0):
        return render_template(
            'notice.html',
            message=CONFIG.get("maintenance_message", ""),
            styles_css=STYLES_CSS_CONTENT,
            script_js=SCRIPT_JS_CONTENT
        )
    return None

@app.before_request
def block_cloudflare_noise():
    if request.path.startswith('/cdn-cgi/'):
        return '', 404

@app.after_request
def set_cache_headers(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def home():
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response

    error = session.pop('error', None)

    app_version = CONFIG.get("version", "1.0.0")
    config = CONFIG.copy()
    banner_image = ""

    bst_tz = pytz.timezone('Asia/Dhaka')
    bst_now = datetime.now(bst_tz)
    min_date = bst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    max_date = min_date + timedelta(days=10)
    bst_midnight_utc = min_date.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')

    # No need to manage 'form_submitted' flag in session for this flow
    form_values = session.get('form_values', {})
    if not form_values:
        form_values = None

    return render_template(
        'index.html',
        error=error,
        app_version=app_version,
        CONFIG=config,
        banner_image=banner_image,
        min_date=min_date.strftime("%Y-%m-%d"),
        max_date=max_date.strftime("%Y-%m-%d"),
        bst_midnight_utc=bst_midnight_utc,
        show_disclaimer=True,
        form_values=form_values,
        trains=trains,
        styles_css=STYLES_CSS_CONTENT,
        script_js=SCRIPT_JS_CONTENT
    )

@app.route('/matrix', methods=['POST'])
def matrix():
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response

    train_model_full = request.form.get('train_model', '').strip()
    journey_date_str = request.form.get('date', '').strip()

    if not train_model_full or not journey_date_str:
        session['error'] = "Both Train Name and Journey Date are required."
        return redirect(url_for('home'))

    try:
        date_obj = datetime.strptime(journey_date_str, '%d-%b-%Y')
        api_date_format = date_obj.strftime('%Y-%m-%d')
    except ValueError:
        session['error'] = "Invalid date format. Use DD-MMM-YYYY (e.g. 15-Nov-2024)."
        return redirect(url_for('home'))

    model_match = re.match(r'.*\((\d+)\)$', train_model_full)
    if model_match:
        train_model = model_match.group(1)
    else:
        train_model = train_model_full.split('(')[0].strip()

    # Store form values in session for potential re-use on the home page if there's an error
    session['form_values'] = {
        'train_model': train_model_full,
        'date': journey_date_str
    }

    # Generate a deterministic request_id based on the search criteria.
    # This ID ensures that the same search always maps to the same cache entry.
    request_id_components = f"{train_model}-{api_date_format}"
    request_id = hashlib.md5(request_id_components.encode('utf-8')).hexdigest()

    # Add the request to the queue. The queue's worker will process it
    # and store the result using this request_id in its internal `self.results` cache.
    request_queue.add_request(
        request_id,
        compute_matrix,
        train_model=train_model,
        journey_date_str=journey_date_str,
        api_date_format=api_date_format
    )

    # Redirect to the matrix_result page with all necessary parameters in the URL.
    # This makes the URL refreshable and shareable, as all required info is in the URL.
    return redirect(url_for('matrix_result',
                            train_model=train_model,
                            journey_date=journey_date_str,
                            api_date_format=api_date_format,
                            train_model_full=train_model_full, # Pass full name for display
                            request_id=request_id)) # Pass the deterministic request_id


@app.route('/matrix_result')
def matrix_result():
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response

    # Retrieve all necessary parameters from the URL query string
    train_model = request.args.get('train_model')
    journey_date_str = request.args.get('journey_date')
    api_date_format = request.args.get('api_date_format')
    train_model_full = request.args.get('train_model_full')
    request_id = request.args.get('request_id') # Get the deterministic ID

    # Validate that all required parameters are present
    if not all([train_model, journey_date_str, api_date_format, train_model_full, request_id]):
        session['error'] = "Missing or invalid search criteria. Please search again."
        return redirect(url_for('home'))

    # Prepare form_values dictionary to pre-populate the search form if user navigates back
    form_values = {
        'train_model': train_model_full,
        'date': journey_date_str
    }

    result = None
    try:
        # Attempt to get the result from the request queue's internal cache using the deterministic ID.
        result = request_queue.get_result(request_id) #

        if not result:
            # If the result is not in the cache (e.g., first access, or cache was cleaned up),
            # re-add the request to the queue and wait for the result.
            # This ensures that refreshing the page will trigger a re-computation if needed.
            request_queue.add_request(
                request_id,
                compute_matrix,
                train_model=train_model,
                journey_date_str=journey_date_str,
                api_date_format=api_date_format
            )
            # Wait for the result. Increase timeout if computations can be very long.
            # This makes the request synchronous and will block until the result is available.
            result = request_queue.wait_for_result(request_id, timeout=120) #

        if not result:
            session['error'] = "Could not retrieve seat matrix. The request timed out or failed to process."
            return redirect(url_for('home'))

    except Exception as e:
        # Catch any exceptions during the data retrieval or computation process
        app.logger.error(f"Error retrieving matrix for {train_model_full} on {journey_date_str}: {e}")
        session['error'] = f"An error occurred: {str(e)}. Please try again."
        return redirect(url_for('home'))

    # Render the matrix.html template with the retrieved result data
    return render_template(
        'matrix.html',
        **result, # Unpack the result dictionary to pass its contents as individual template variables
        form_values=form_values,
        styles_css=STYLES_CSS_CONTENT,
        script_js=SCRIPT_JS_CONTENT
    )

# ... (rest of your app.py code for /queue_stats, /queue_cleanup, errorhandler, etc.) ...
