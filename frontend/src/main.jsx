import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// Global error handler to capture uncaught errors
window.addEventListener('error', (event) => {
  console.error('Uncaught error:', event.error);
  // Send to backend for logging
  fetch('/api/frontend-error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: event.error?.stack,
      timestamp: new Date().toISOString(),
    }),
  }).catch(() => {});
});

window.addEventListener('unhandledrejection', (event) => {
  console.error('Unhandled rejection:', event.reason);
  fetch('/api/frontend-error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: event.reason?.message || String(event.reason),
      stack: event.reason?.stack,
      timestamp: new Date().toISOString(),
    }),
  }).catch(() => {});
});

// Override console.error to also send to backend
const originalConsoleError = console.error;
console.error = (...args) => {
  originalConsoleError.apply(console, args);
  try {
    fetch('/api/frontend-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' '),
        timestamp: new Date().toISOString(),
      }),
    }).catch(() => {});
  } catch (e) {
    // Ignore fetch errors
  }
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);