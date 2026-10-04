import { useEffect, useRef, useCallback } from 'react';

export function useEventStream(onEvent) {
  const wsRef = useRef(null);
  const sseRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const onEventRef = useRef(onEvent);

  onEventRef.current = onEvent;

  const connectWS = useCallback(() => {
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onEventRef.current(data);
      } catch (e) {
        console.error('WS message parse error:', e);
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting...');
      reconnectTimeoutRef.current = setTimeout(connectWS, 3000);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };
  }, []);

  const connectSSE = useCallback(() => {
    const eventSource = new EventSource(`${window.location.origin}/api/events/stream`);
    sseRef.current = eventSource;

    eventSource.onopen = () => {
      console.log('SSE connected');
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onEventRef.current(data);
      } catch (e) {
        console.error('SSE message parse error:', e);
      }
    };

    eventSource.onerror = () => {
      console.log('SSE disconnected, reconnecting...');
      eventSource.close();
      reconnectTimeoutRef.current = setTimeout(connectSSE, 3000);
    };
  }, []);

  useEffect(() => {
    connectWS();
    connectSSE();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (sseRef.current) {
        sseRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connectWS, connectSSE]);
}