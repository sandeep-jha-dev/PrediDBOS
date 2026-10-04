import { FileJson, Copy, Check } from 'lucide-react';
import { useState } from 'react';
import { clsx } from 'clsx';

const syntaxHighlight = (json) => {
  if (typeof json !== 'string') {
    json = JSON.stringify(json, null, 2);
  }
  return json
    .replace(/&/g, '&')
    .replace(/</g, '<')
    .replace(/>/g, '>')
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, (match) => {
      let cls = 'json-number';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'json-key';
        } else {
          cls = 'json-string';
        }
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean';
      } else if (/null/.test(match)) {
        cls = 'json-null';
      }
      return `<span class="${cls}">${match}</span>`;
    });
};

export default function HintPanel({ predictions }) {
  const [copied, setCopied] = useState(false);
  const latest = predictions[0];

  const hintJson = latest ? {
    prediction_id: latest.id,
    timestamp: latest.timestamp,
    predicted_object: latest.predicted_object,
    access_pattern: latest.predicted_access_pattern,
    confidence: latest.confidence,
    model_version: latest.model_version,
  } : {};

  const copyToClipboard = () => {
    navigator.clipboard.writeText(JSON.stringify(hintJson, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="card h-full flex flex-col">
      <div className="card-header flex items-center justify-between">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <FileJson className="w-5 h-5 text-gray-500" />
          Workload Hint (JSON)
        </h3>
        <button 
          onClick={copyToClipboard}
          className="btn-secondary text-xs flex items-center gap-1"
          title="Copy to clipboard"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline">{copied ? 'Copied!' : 'Copy'}</span>
        </button>
      </div>
      <div className="card-body flex-1 overflow-hidden">
        <div className="json-viewer scrollbar-thin" dangerouslySetInnerHTML={{ __html: syntaxHighlight(hintJson) }} />
        {!latest && (
          <div className="flex items-center justify-center h-full text-gray-500">
            <p className="text-sm">No hint generated yet</p>
          </div>
        )}
      </div>
    </div>
  );
}