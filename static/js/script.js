// static/js/script.js

document.addEventListener('DOMContentLoaded', function() {
    // --- Common Functions for all pages (if needed) ---
    // Example: Add a class to body for better styling control or handle general alerts
    const errorMessage = document.getElementById('error-message');
    if (errorMessage && errorMessage.textContent.trim() !== '') {
        // You can add more complex error display logic here
        console.error("Server-side error:", errorMessage.textContent);
    }

    // --- Specific Logic for Queue Wait Page ---
    const queuePage = document.getElementById('queue-wait-page');
    if (queuePage) {
        const requestId = queuePage.dataset.requestId;
        const statusElement = document.getElementById('queue-status-text');
        const spinner = document.getElementById('loading-spinner');
        const progressBar = document.getElementById('progress-bar');
        const queuePositionElement = document.getElementById('queue-position');
        const estimatedTimeElement = document.getElementById('estimated-time');
        const backToHomeButton = document.getElementById('back-to-home-btn');

        let pollInterval;
        let lastStatus = '';
        let dots = 0; // For animating dots after status message

        const updateStatusMessage = (status, position = null, estimatedTime = null) => {
            let message = '';
            let progress = 0;

            switch (status) {
                case 'pending':
                    message = 'In queue';
                    if (position !== null && position > 0) {
                        message += `, position ${position}`;
                        if (estimatedTime !== null) {
                            message += ` (Est. ${estimatedTime}s)`;
                        }
                    }
                    progress = 25; // Example progress
                    break;
                case 'processing':
                    message = 'Processing your request';
                    progress = 75; // Example progress
                    break;
                case 'completed':
                    message = 'Request completed! Redirecting...';
                    progress = 100;
                    break;
                case 'failed':
                    message = 'Request failed. Please try again.';
                    progress = 100;
                    break;
                case 'cancelled':
                    message = 'Request cancelled.';
                    progress = 100;
                    break;
                default:
                    message = 'Checking status...';
                    progress = 10;
            }

            // Animate dots for pending/processing status
            if (status === 'pending' || status === 'processing') {
                dots = (dots + 1) % 4; // Cycle 0, 1, 2, 3
                statusElement.textContent = message + '.'.repeat(dots);
            } else {
                statusElement.textContent = message;
            }

            // Update progress bar
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
                progressBar.setAttribute('aria-valuenow', progress);
                if (progress === 100) {
                    progressBar.classList.remove('bg-blue-500');
                    progressBar.classList.add('bg-green-500');
                } else {
                    progressBar.classList.add('bg-blue-500');
                    progressBar.classList.remove('bg-green-500');
                }
            }

            // Update specific position/time elements
            if (queuePositionElement) {
                queuePositionElement.textContent = position !== null ? `Position: ${position}` : 'N/A';
            }
            if (estimatedTimeElement) {
                estimatedTimeElement.textContent = estimatedTime !== null ? `Estimated Time: ${estimatedTime}s` : 'N/A';
            }
        };

        const pollQueueStatus = async () => {
            if (!requestId) {
                clearInterval(pollInterval);
                statusElement.textContent = 'Invalid request ID. Redirecting to home...';
                setTimeout(() => window.location.href = '/', 2000);
                return;
            }

            try {
                const response = await fetch(`/queue_status/${requestId}`);
                const data = await response.json();

                if (data.error) {
                    clearInterval(pollInterval);
                    statusElement.textContent = `Error: ${data.error}`;
                    if (spinner) spinner.style.display = 'none';
                    if (backToHomeButton) backToHomeButton.style.display = 'block';
                    setTimeout(() => window.location.href = '/', 3000); // Redirect on hard error
                    return;
                }

                updateStatusMessage(data.status, data.position, data.estimated_time);

                if (data.status === 'completed') {
                    clearInterval(pollInterval);
                    if (spinner) spinner.style.display = 'none';

                    if (data.redirect_params) {
                        const params = new URLSearchParams({
                            request_id: data.redirect_params.request_id,
                            train_name: data.redirect_params.train_name,
                            date: data.redirect_params.date
                        }).toString();
                        // Redirect to the /show_results route with all necessary parameters
                        window.location.href = `/show_results?${params}`;
                    } else {
                        // Fallback if redirect_params are missing (shouldn't happen with updated app.py)
                        statusElement.textContent = 'Request completed, but redirect data missing. Redirecting to home...';
                        setTimeout(() => window.location.href = '/', 2000);
                    }
                } else if (data.status === 'failed' || data.status === 'cancelled') {
                    clearInterval(pollInterval);
                    if (spinner) spinner.style.display = 'none';
                    // Display specific error message if available from backend
                    if (data.errorMessage) {
                         statusElement.textContent = `Error: ${data.errorMessage}`;
                    }
                    if (backToHomeButton) backToHomeButton.style.display = 'block';
                    // Redirect to home after a short delay
                    setTimeout(() => window.location.href = '/', 3000);
                } else {
                    // Update heartbeat for active requests
                    if (data.status !== lastStatus && (data.status === 'pending' || data.status === 'processing')) {
                        // Only send heartbeat if status changed to active state
                        await fetch(`/queue_heartbeat/${requestId}`, { method: 'POST' });
                        lastStatus = data.status; // Update lastStatus
                    }
                }

            } catch (error) {
                clearInterval(pollInterval);
                statusElement.textContent = 'Failed to connect to server. Please try again.';
                console.error('Polling error:', error);
                if (spinner) spinner.style.display = 'none';
                if (backToHomeButton) backToHomeButton.style.display = 'block';
                setTimeout(() => window.location.href = '/', 3000); // Redirect on network error
            }
        };

        // Initial call and then set up polling
        pollQueueStatus();
        // Poll every 3 seconds (adjust as needed based on expected queue times)
        pollInterval = setInterval(pollQueueStatus, 3000);

        // --- Handle page unload/close to cancel request (optional but good practice) ---
        window.addEventListener('beforeunload', async (event) => {
            if (requestId) {
                // Use navigator.sendBeacon for reliable fire-and-forget request on unload
                // This doesn't guarantee the server receives it, but it's best effort.
                navigator.sendBeacon(`/cancel_request_beacon/${requestId}`);
            }
        });
    }

    // --- Common UI interactions ---
    // Example: For the date input, ensure min/max dates are applied correctly
    const journeyDateInput = document.getElementById('journey_date');
    if (journeyDateInput) {
        // This is handled by Flask's render_template now, but good to have client-side fallback/check
        const today = new Date();
        const yyyy = today.getFullYear();
        let mm = today.getMonth() + 1; // Months start at 0!
        let dd = today.getDate();

        if (mm < 10) mm = '0' + mm;
        if (dd < 10) dd = '0' + dd;

        const formattedToday = `${yyyy}-${mm}-${dd}`;
        journeyDateInput.setAttribute('min', formattedToday);
        // You might set max date here if not done by Flask for 10 days ahead
        // let maxDate = new Date();
        // maxDate.setDate(today.getDate() + 10);
        // const max_yyyy = maxDate.getFullYear();
        // let max_mm = maxDate.getMonth() + 1;
        // let max_dd = maxDate.getDate();
        // if (max_mm < 10) max_mm = '0' + max_mm;
        // if (max_dd < 10) max_dd = '0' + max_dd;
        // journeyDateInput.setAttribute('max', `${max_yyyy}-${max_mm}-${max_dd}`);
    }

    // Example: Event listener for train name dropdown if dynamic behavior is needed
    const trainNameSelect = document.getElementById('train_name');
    if (trainNameSelect) {
        trainNameSelect.addEventListener('change', function() {
            // Add any JavaScript logic here that depends on train selection
            console.log('Train selected:', this.value);
        });
    }

});
