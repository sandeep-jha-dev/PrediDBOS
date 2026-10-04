import { useState, Component } from 'react';
import { AlertCircle, RefreshCw, Bug } from 'lucide-react';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    this.setState({ errorInfo });
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 border border-red-200">
            <div className="flex items-center gap-3 mb-4">
              <div className="flex items-center justify-center w-12 h-12 rounded-full bg-red-100">
                <Bug className="w-6 h-6 text-red-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">Runtime Error</h2>
                <p className="text-sm text-gray-500">The dashboard encountered an error and stopped rendering.</p>
              </div>
            </div>
            
            <div className="bg-gray-100 rounded-lg p-4 mb-4 max-h-64 overflow-auto">
              <pre className="text-xs text-red-700 font-mono whitespace-pre-wrap">{this.state.error?.toString()}</pre>
              {this.state.errorInfo && (
                <pre className="text-xs text-gray-600 font-mono whitespace-pre-wrap mt-2">{this.state.errorInfo.componentStack}</pre>
              )}
            </div>

            <button 
              onClick={this.handleRetry}
              className="w-full btn-primary flex items-center justify-center gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              Reload Dashboard
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;