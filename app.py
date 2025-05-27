# app.py
from flask import Flask, render_template, request, redirect, url_for
import datetime

app = Flask(__name__)

# --- Simulated Data ---
# In a real application, this would come from a database or an external API.
# This dictionary simulates train seat availability for demonstration purposes.
SIMULATED_TRAIN_DATA = {
    "Intercity Express": {
        "2025-06-01": [
            {"coach": "A", "seat_number": "1A", "status": "Available"},
            {"coach": "A", "seat_number": "1B", "status": "Booked"},
            {"coach": "B", "seat_number": "2C", "status": "Available"},
        ],
        "2025-06-02": [
            {"coach": "A", "seat_number": "1A", "status": "Booked"},
            {"coach": "A", "seat_number": "1B", "status": "Available"},
            {"coach": "C", "seat_number": "3D", "status": "Available"},
        ],
    },
    "Local Shuttle": {
        "2025-06-01": [
            {"coach": "L1", "seat_number": "1", "status": "Available"},
            {"coach": "L1", "seat_number": "2", "status": "Booked"},
        ],
        "2025-06-03": [
            {"coach": "L1", "seat_number": "1", "status": "Booked"},
            {"coach": "L2", "seat_number": "5", "status": "Available"},
        ],
    },
}

# --- Routes ---

@app.route('/')
def index():
    """
    Renders the main search form page.
    """
    # Get today's date to pre-fill the date input
    today = datetime.date.today().isoformat()
    return render_template('index.html', today=today)

@app.route('/search', methods=['POST'])
def search_trains():
    """
    Handles the form submission from the index page.
    Redirects to the results page with search criteria as query parameters.
    """
    train_name = request.form.get('train_name')
    journey_date = request.form.get('journey_date')

    if not train_name or not journey_date:
        # Basic validation: if data is missing, redirect back to index with an error (optional)
        # For simplicity, we'll just redirect to index. In a real app, you'd show a message.
        return redirect(url_for('index'))

    # Redirect to the results page, passing criteria as query parameters.
    # This makes the URL refreshable with the same criteria.
    return redirect(url_for('show_results', train_name=train_name, journey_date=journey_date))

@app.route('/results')
def show_results():
    """
    Displays the train seat availability results.
    Retrieves search criteria from URL query parameters.
    """
    train_name = request.args.get('train_name')
    journey_date = request.args.get('journey_date')

    seat_data = []
    message = ""

    if train_name and journey_date:
        # Simulate fetching data based on the provided criteria
        if train_name in SIMULATED_TRAIN_DATA:
            if journey_date in SIMULATED_TRAIN_DATA[train_name]:
                seat_data = SIMULATED_TRAIN_DATA[train_name][journey_date]
                if not seat_data:
                    message = f"No seat data found for {train_name} on {journey_date}."
            else:
                message = f"No journeys found for {train_name} on {journey_date}."
        else:
            message = f"Train '{train_name}' not found in our system."
    else:
        message = "Your request is incomplete. Please search again from the home page."
        # Optionally redirect back to index if criteria are missing on direct access
        # return redirect(url_for('index'))

    return render_template('results.html',
                           train_name=train_name,
                           journey_date=journey_date,
                           seat_data=seat_data,
                           message=message)

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True) # debug=True automatically reloads the server on code changes
