# app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime, timedelta
import json, pytz, os, re, uuid
from matrixCalculator import compute_matrix # Assuming this exists and works
from request_queue import RequestQueue     # Assuming this exists and works

app = Flask(__name__)
app.secret_key = "super_secret_key" # IMPORTANT: Change this to a strong, random key in production!

# Global caches and configs
RESULT_CACHE = {} # You can remove this if RequestQueue handles all result storage
                  # It seems your RequestQueue already stores results, so this might be redundant.

with open('config.json', 'r', encoding='utf-8') as config_file:
    CONFIG = json.load(config_file)

# Pre-load CSS/JS content - this is fine for small files, but for larger apps,
# Flask's static file serving is more typical.
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
    # This line seems unnecessary if you're not passing it to JS for specific use
    # bst_midnight_utc = min_date.astimezone(pytz.UTC).strftime('%Y-%m-%dT%H:%M:%SZ') 

    # We will no longer rely on session['form_submitted'] for fresh forms.
    # The home page always starts fresh for a new search.
    session.pop('form_values', None) # Clear any old form values from session

    # form_values are generally not needed on the home page for a fresh search,
    # unless you want to pre-fill from a previous *successful* search.
    # If you want to retain form values, you'd pull them from session or URL params
    # only after a successful result display.
    form_values = None 

    return render_template(
        'index.html',
        error=error,
        app_version=app_version,
        CONFIG=config,
        banner_image=banner_image,
        min_date=min_date.strftime("%Y-%m-%d"),
        max_date=max_date.strftime("%Y-%m-%d"),
        # bst_midnight_utc=bst_midnight_utc, # Remove if not used
        show_disclaimer=True,
        form_values=form_values, # This will be None on initial load
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
        # Date format parsing remains the same
        date_obj = datetime.strptime(journey_date_str, '%d-%b-%Y')
        api_date_format = date_obj.strftime('%Y-%m-%d')
    except ValueError:
        session['error'] = "Invalid date format. Use DD-MMM-YYYY (e.g. 15-Nov-2024)."
        return redirect(url_for('home'))

    model_match = re.match(r'.*\((\d+)\)$', train_model_full)
    if model_match:
        train_model_code = model_match.group(1) # Using a new variable name for clarity
    else:
        train_model_code = train_model_full.split('(')[0].strip()

    try:
        form_values = {
            'train_model_full': train_model_full, # Keep the full name for display
            'train_model_code': train_model_code, # Keep the code for API call
            'date': journey_date_str,
            'api_date_format': api_date_format # Store this too
        }
        # Store form_values in session, but only for the duration of the queue process
        session['form_values'] = form_values

        request_id = request_queue.add_request(
            process_matrix_request,
            {
                'train_model_code': train_model_code, # Use code for compute_matrix
                'journey_date_str': journey_date_str,
                'api_date_format': api_date_format,
                'form_values': form_values # Pass form_values to the queued function
            }
        )
        
        session['queue_request_id'] = request_id
        
        # Redirect to queue_wait. The show_results will handle the final display.
        return redirect(url_for('queue_wait'))
    except Exception as e:
        session['error'] = f"{str(e)}"
        return redirect(url_for('home'))

def process_matrix_request(train_model_code, journey_date_str, api_date_format, form_values):
    """
    This function is run by the RequestQueue.
    It takes the criteria and calls compute_matrix.
    """
    try:
        # Use train_model_code for compute_matrix as that's what your regex extracted.
        result = compute_matrix(train_model_code, journey_date_str, api_date_format)
        if not result or 'stations' not in result:
            return {"error": "No data received. Please try a different train or date."}
        
        return {"success": True, "result": result, "form_values": form_values}
    except Exception as e:
        return {"error": str(e)}

@app.route('/queue_wait')
def queue_wait():
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response
    
    request_id = session.get('queue_request_id')
    
    # If no request_id in session, it means they might have refreshed queue_wait directly
    # or came from a page without starting a search.
    if not request_id:
        session['error'] = "Your request session has expired or was not initiated. Please search again."
        return redirect(url_for('home'))
    
    status = request_queue.get_request_status(request_id)
    
    # If the request_id exists but the status is gone (e.g., cleaned up by queue),
    # or if the request is completed, redirect to show_results with parameters.
    if not status or status["status"] == "completed":
        queue_result = request_queue.get_request_result(request_id)
        if queue_result and queue_result.get("success"):
            form_vals = queue_result.get("form_values", {})
            train_name_full = form_vals.get('train_model_full', '')
            journey_date = form_vals.get('date', '')
            # Pass train_name_full and journey_date to the results page
            return redirect(url_for('show_results', request_id=request_id,
                                    train_name=train_name_full, date=journey_date))
        else:
            # If request failed or no successful result, show error and redirect home.
            session['error'] = queue_result.get("error", "An unknown error occurred after processing.")
            return redirect(url_for('home'))

    # If status is not completed, stay on queue page.
    # The 'refresh_check' logic should be handled by client-side JS on queue.html,
    # or ideally, not block on a server-side redirect for mere refresh.
    # The current 'refresh_check' logic essentially cancels the request if you refresh,
    # which is likely the cause of your issue. We need to modify this.
    
    # --- IMPORTANT CHANGE HERE ---
    # Remove or modify the 'refresh_check' logic to avoid cancelling on simple refresh.
    # If the user refreshes queue_wait, they just want an updated queue status, not a cancellation.
    # The current code below is problematic:
    # if request.args.get('refresh_check') == 'true':
    #     request_queue.cancel_request(request_id)
    #     session.pop('queue_request_id', None)
    #     session['error'] = "Page was refreshed. Please start a new search."
    #     return redirect(url_for('home'))
    # --- END IMPORTANT CHANGE ---
    
    form_values = session.get('form_values', {}) # Keep form_values for queue display
    
    return render_template(
        'queue.html',
        request_id=request_id,
        status=status, 
        form_values=form_values,
        styles_css=STYLES_CSS_CONTENT,
        script_js=SCRIPT_JS_CONTENT
    )

@app.route('/queue_status/<request_id>')
def queue_status_api(request_id): # Renamed to avoid conflict with queue_wait route
    status = request_queue.get_request_status(request_id)
    if not status:
        return jsonify({"error": "Request not found"}), 404
    
    if status["status"] == "failed":
        result = request_queue.get_request_result(request_id)
        if result and "error" in result:
            status["errorMessage"] = result["error"]
            
    # If the request is completed, return the result directly via this API endpoint
    # so the client-side JS can trigger the redirect.
    if status["status"] == "completed":
        completed_result = request_queue.get_request_result(request_id)
        if completed_result and completed_result.get("success"):
            # Ensure form_values are sent back so client can redirect to show_results with them
            status["redirect_params"] = {
                "request_id": request_id,
                "train_name": completed_result["form_values"].get("train_model_full", ""),
                "date": completed_result["form_values"].get("date", "")
            }
        else:
            status["error_message"] = completed_result.get("error", "Failed to retrieve results.")
    
    return jsonify(status)

@app.route('/cancel_request/<request_id>', methods=['POST'])
def cancel_request(request_id):
    try:
        removed = request_queue.cancel_request(request_id)
        
        if session.get('queue_request_id') == request_id:
            session.pop('queue_request_id', None)
        
        stats = request_queue.get_queue_stats()
        if stats.get('cancelled_pending', 0) > 5:
            request_queue.force_cleanup()
        
        return jsonify({"cancelled": removed, "status": "success"})
    except Exception as e:
        return jsonify({"cancelled": False, "status": "error", "error": str(e)}), 500

@app.route('/cancel_request_beacon/<request_id>', methods=['POST'])
def cancel_request_beacon(request_id):
    try:
        request_queue.cancel_request(request_id)
        return '', 204
    except Exception:
        return '', 204

@app.route('/queue_heartbeat/<request_id>', methods=['POST'])
def queue_heartbeat(request_id):
    try:
        updated = request_queue.update_heartbeat(request_id)
        return jsonify({"status": "success", "active": updated})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# Modified /show_results route
@app.route('/show_results')
@app.route('/show_results/<request_id>')
def show_results(request_id=None): # request_id is now optional
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response

    result = {}
    form_values = {}
    message = ""

    # Attempt to retrieve from queue cache using request_id from URL or session
    if request_id:
        queue_result = request_queue.get_request_result(request_id)
        if queue_result and queue_result.get("success"):
            result = queue_result.get("result", {})
            form_values = queue_result.get("form_values", {})
            # Remove from session if we are displaying a direct ID result (optional, depends on caching strategy)
            if session.get('queue_request_id') == request_id:
                session.pop('queue_request_id', None)
            
            # Since we found a cached result, display it
            return render_template(
                'matrix.html',
                **result, # Unpack the result dictionary (stations, etc.)
                form_values=form_values,
                styles_css=STYLES_CSS_CONTENT,
                script_js=SCRIPT_JS_CONTENT
            )
        elif queue_result and "error" in queue_result:
            # If queue result exists but indicates an error
            message = queue_result["error"]
            # Fall through to try re-calculation from URL parameters

    # If no valid request_id result, or if it failed, try to re-process from URL parameters
    # This handles direct access, refresh, or failed queue lookup.
    train_name_full = request.args.get('train_name', '').strip() # This is the full train name from URL
    journey_date_str = request.args.get('date', '').strip()     # This is the date from URL

    if train_name_full and journey_date_str:
        try:
            # Re-extract train_model_code as it's needed for compute_matrix
            model_match = re.match(r'.*\((\d+)\)$', train_name_full)
            if model_match:
                train_model_code = model_match.group(1)
            else:
                train_model_code = train_name_full.split('(')[0].strip()

            date_obj = datetime.strptime(journey_date_str, '%d-%b-%Y') # Original format
            api_date_format = date_obj.strftime('%Y-%m-%d') # Format for API

            # Re-compute the matrix directly
            result = compute_matrix(train_model_code, journey_date_str, api_date_format)
            if not result or 'stations' not in result:
                message = "No data received for these criteria. Please try again."
            else:
                form_values = {
                    'train_model_full': train_name_full,
                    'train_model_code': train_model_code,
                    'date': journey_date_str,
                    'api_date_format': api_date_format
                }
                # Display the re-computed result
                return render_template(
                    'matrix.html',
                    **result,
                    form_values=form_values,
                    styles_css=STYLES_CSS_CONTENT,
                    script_js=SCRIPT_JS_CONTENT
                )
        except ValueError:
            message = "Invalid date format in URL. Please search again."
        except Exception as e:
            message = f"An error occurred while re-fetching data: {str(e)}"
    else:
        message = message or "Your request has expired or could not be found. Please search again from home."
        # If no request_id and no URL params, or an error, show message and redirect to home.
        session['error'] = message
        return redirect(url_for('home'))

    # If we reached here, it means either a cached result wasn't found and re-computation failed
    # or initial message was set due to error.
    session['error'] = message # Ensure the error message is passed to home
    return redirect(url_for('home'))


# Your existing routes below this are likely fine as they are.
# @app.route('/matrix_result') - This route seems redundant now that show_results handles everything.
#                                Consider removing it to simplify your app.
#                                If it's for an older flow, you might need to update its callers.
# Your code uses RESULT_CACHE.pop(result_id, None) which means it's one-time use.
# The new show_results route will either use the queue's stored result or re-calculate.


# @app.route('/matrix_result') # <--- Consider removing this route
# def matrix_result():
#     maintenance_response = check_maintenance()
#     if maintenance_response:
#         return maintenance_response
#
#     result_id = session.pop('result_id', None)
#     result = RESULT_CACHE.pop(result_id, None) if result_id else None
#     form_values = session.get('form_values', None)
#
#     if not result:
#         return redirect(url_for('home'))
#
#     return render_template(
#         'matrix.html',
#         **result,
#         form_values=form_values,
#         styles_css=STYLES_CSS_CONTENT,
#         script_js=SCRIPT_JS_CONTENT
#     )

@app.route('/queue_stats')
def queue_stats():
    try:
        stats = request_queue.get_queue_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue_cleanup', methods=['POST'])
def queue_cleanup():
    try:
        request_queue.force_cleanup()
        stats = request_queue.get_queue_stats()
        return jsonify({"status": "success", "message": "Cleanup completed", "stats": stats})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.errorhandler(404)
def page_not_found(e):
    maintenance_response = check_maintenance()
    if maintenance_response:
        return maintenance_response
    return render_template('404.html', styles_css=STYLES_CSS_CONTENT, script_js=SCRIPT_JS_CONTENT), 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
