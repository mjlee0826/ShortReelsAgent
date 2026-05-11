import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { LogtoProvider } from '@logto/react';
import './index.css';
import App from './App.jsx';

const logtoConfig = {
  endpoint:  import.meta.env.VITE_LOGTO_ENDPOINT  || '',
  appId:     import.meta.env.VITE_LOGTO_APP_ID    || '',
  resources: [import.meta.env.VITE_LOGTO_API_RESOURCE || ''],
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
