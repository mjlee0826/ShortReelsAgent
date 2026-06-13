import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { LogtoProvider } from '@logto/react';
import './index.css';
import App from './App.jsx';
import { LOGTO_ENDPOINT, LOGTO_APP_ID, API_RESOURCE } from './config/env';

const logtoConfig = {
  endpoint: LOGTO_ENDPOINT,
  appId: LOGTO_APP_ID,
  resources: [API_RESOURCE || ''],
};

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <LogtoProvider config={logtoConfig}>
        <App />
      </LogtoProvider>
    </BrowserRouter>
  </StrictMode>,
);
