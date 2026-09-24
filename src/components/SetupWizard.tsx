import React, { useState, useEffect } from "react";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis";

export interface ProviderOption {
  id: string;
  name: string;
  badge: "FREE" | "PAID";
  description: string;
  portalUrl: string;
  instructions: string[];
  keyPrefix?: string;
  placeholder?: string;
}

export const PROVIDERS: ProviderOption[] = [
  {
    id: "gemini",
    name: "Gemini",
    badge: "FREE",
    description: "Fast, powerful, and includes generous free usage limits.",
    portalUrl: "https://aistudio.google.com/app/apikey",
    keyPrefix: "AIzaSy",
    placeholder: "AIzaSy...",
    instructions: [
      "Open Google AI Studio to generate your free Gemini API key.",
      "Create or copy your key from the API keys dashboard.",
      "Paste your key into the box below and click Test & Save.",
    ],
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    badge: "FREE",
    description: "Access hundreds of models with free open-source tier options.",
    portalUrl: "https://openrouter.ai/keys",
    keyPrefix: "sk-or-",
    placeholder: "sk-or-...",
    instructions: [
      "Visit OpenRouter to create an account API key.",
      "Generate a new key in your Account API Keys settings.",
      "Paste your key into the box below and click Test & Save.",
    ],
  },
  {
    id: "openai",
    name: "OpenAI",
    badge: "PAID",
    description: "Industry-standard GPT-4o models for high reasoning capabilities.",
    portalUrl: "https://platform.openai.com/api-keys",
    keyPrefix: "sk-",
    placeholder: "sk-...",
    instructions: [
      "Open your OpenAI API platform dashboard.",
      "Create a secret API key under the 'API keys' section.",
      "Paste your key into the box below and click Test & Save.",
    ],
  },
  {
    id: "anthropic",
    name: "Anthropic",
    badge: "PAID",
    description: "Claude 3.5 Haiku and Sonnet for precise code and analysis.",
    portalUrl: "https://console.anthropic.com/settings/keys",
    keyPrefix: "sk-ant-",
    placeholder: "sk-ant-...",
    instructions: [
      "Sign in to the Anthropic Console dashboard.",
      "Generate an API key under Account Settings -> API Keys.",
      "Paste your key into the box below and click Test & Save.",
    ],
  },
  {
    id: "ollama",
    name: "Ollama",
    badge: "FREE",
    description: "100% private, on-device AI running on your local machine.",
    portalUrl: "https://ollama.com/download",
    instructions: [
      "Make sure Ollama is installed and running locally on your computer.",
      "Ollama listens on http://localhost:11434 by default.",
      "HeyBloopie will auto-detect your local models without needing an API key.",
    ],
  },
];

export interface SetupWizardProps {
  initialProvider?: string;
  onComplete?: (provider: string) => void;
  onCancel?: () => void;
  invokeFn?: (cmd: string, args?: any) => Promise<any>;
}

export const SetupWizard: React.FC<SetupWizardProps> = ({
  initialProvider = "gemini",
  onComplete,
  onCancel,
  invokeFn,
}) => {
  // Screen state: 1 (Choose Provider) or 2 (Set Up Provider)
  const [currentScreen, setCurrentScreen] = useState<1 | 2>(1);
  const [selectedProviderId, setSelectedProviderId] = useState<string>(initialProvider);
  const [apiKey, setApiKey] = useState<string>("");
  const [showKey, setShowKey] = useState<boolean>(false);

  // Validation / async status state
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState<boolean>(false);

  // Ollama state
  const [isCheckingOllama, setIsCheckingOllama] = useState<boolean>(false);
  const [ollamaDetected, setOllamaDetected] = useState<boolean>(false);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);

  const { speak } = useSpeechSynthesis();

  const selectedProvider =
    PROVIDERS.find((p) => p.id === selectedProviderId) || PROVIDERS[0];

  // Helper to execute Tauri invoke calls safely
  const callTauri = async (cmd: string, args?: any): Promise<any> => {
    if (invokeFn) {
      return invokeFn(cmd, args);
    }
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      return await invoke(cmd, args);
    } catch (err) {
      console.warn(`Tauri invoke('${cmd}') fallback:`, err);
      throw err;
    }
  };

  // Run Ollama detection when Screen 2 opens for Ollama
  useEffect(() => {
    if (currentScreen === 2 && selectedProvider.id === "ollama") {
      checkOllamaServer();
    }
  }, [currentScreen, selectedProvider.id]);

  const checkOllamaServer = async () => {
    setIsCheckingOllama(true);
    setErrorMessage(null);
    try {
      const res = await callTauri("check_ollama");
      if (res && res.detected) {
        setOllamaDetected(true);
        setOllamaModels(res.models || []);
      } else {
        setOllamaDetected(false);
        setErrorMessage(
          "Ollama server was not detected at http://localhost:11434. Make sure the Ollama application is running."
        );
      }
    } catch (err: any) {
      setOllamaDetected(false);
      setErrorMessage(
        "I can't reach Ollama. Make sure Ollama is installed and running locally."
      );
    } finally {
      setIsCheckingOllama(false);
    }
  };

  const handleContinue = () => {
    setErrorMessage(null);
    setIsSuccess(false);
    setApiKey("");
    setCurrentScreen(2);
  };

  const handleBack = () => {
    setErrorMessage(null);
    setIsSuccess(false);
    setCurrentScreen(1);
  };

  const handleOpenPortal = () => {
    if (typeof window !== "undefined") {
      window.open(selectedProvider.portalUrl, "_blank", "noopener,noreferrer");
    }
  };

  const handleTestAndSave = async () => {
    setErrorMessage(null);
    setIsValidating(true);

    try {
      const res = await callTauri("validate_provider_key", {
        provider: selectedProvider.id,
        key: apiKey.trim(),
      });

      if (res && res.success) {
        setIsSuccess(true);
        speak("Brain connected. I'm ready.");
        if (onComplete) {
          setTimeout(() => {
            onComplete(selectedProvider.id);
          }, 1200);
        }
      } else {
        setErrorMessage(res?.error || "Validation failed. Please check your key.");
      }
    } catch (err: any) {
      const msg = err?.message || String(err);
      setErrorMessage(msg);
    } finally {
      setIsValidating(false);
    }
  };

  const handleOllamaFinish = () => {
    setIsSuccess(true);
    speak("Brain connected. I'm ready.");
    if (onComplete) {
      setTimeout(() => {
        onComplete("ollama");
      }, 800);
    }
  };

  return (
    <div className="setup-wizard-backdrop" data-testid="setup-wizard">
      <div className="setup-wizard-card">
        {/* Navigation / Header */}
        <div className="setup-header">
          {currentScreen === 2 && (
            <button
              className="btn-back"
              onClick={handleBack}
              data-testid="btn-back"
              aria-label="Back"
            >
              ← Back
            </button>
          )}
          <div className="setup-title-group">
            <h2 className="setup-title">
              {currentScreen === 1
                ? "Choose Your AI Brain"
                : `Set Up ${selectedProvider.name}`}
            </h2>
            <p className="setup-subtitle">
              {currentScreen === 1
                ? "HeyBloopie is provider-agnostic. Pick your preferred AI provider to get started."
                : `Connect ${selectedProvider.name} to start managing files with hands-free voice.`}
            </p>
          </div>
          {onCancel && (
            <button className="btn-close" onClick={onCancel} aria-label="Close">
              ✕
            </button>
          )}
        </div>

        {/* SCREEN 1: Choose Provider */}
        {currentScreen === 1 && (
          <div className="screen-1" data-testid="screen-1">
            <div className="provider-grid">
              {PROVIDERS.map((prov) => {
                const isSelected = selectedProviderId === prov.id;
                return (
                  <div
                    key={prov.id}
                    data-testid={`provider-card-${prov.id}`}
                    className={`provider-card ${isSelected ? "selected" : ""}`}
                    onClick={() => setSelectedProviderId(prov.id)}
                  >
                    <div className="card-top">
                      <div className="provider-name-row">
                        <span className="provider-name">{prov.name}</span>
                        <span
                          className={`cost-badge ${
                            prov.badge === "FREE" ? "badge-free" : "badge-paid"
                          }`}
                        >
                          {prov.badge}
                        </span>
                      </div>
                      <div className="radio-indicator">
                        {isSelected && <span className="radio-dot" />}
                      </div>
                    </div>
                    <p className="provider-desc">{prov.description}</p>
                  </div>
                );
              })}
            </div>

            <div className="setup-footer">
              <button
                className="btn-primary"
                onClick={handleContinue}
                data-testid="btn-continue"
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* SCREEN 2: Set Up Selected Provider */}
        {currentScreen === 2 && (
          <div className="screen-2" data-testid="screen-2">
            {/* Provider Instructions */}
            <div className="instructions-box">
              <div className="instructions-header">
                <span className="inst-badge">Quick Setup</span>
                <button
                  className="btn-external"
                  onClick={handleOpenPortal}
                  data-testid="btn-open-portal"
                >
                  Open {selectedProvider.name} ↗
                </button>
              </div>
              <ol className="instructions-list">
                {selectedProvider.instructions.map((step, idx) => (
                  <li key={idx}>{step}</li>
                ))}
              </ol>
            </div>

            {/* Error Message Alert */}
            {errorMessage && (
              <div className="alert-banner alert-error" data-testid="error-message">
                <span className="alert-icon">⚠️</span>
                <span className="alert-text">{errorMessage}</span>
              </div>
            )}

            {/* Success Message Alert */}
            {isSuccess && (
              <div className="alert-banner alert-success" data-testid="success-message">
                <span className="alert-icon">✓</span>
                <span className="alert-text">
                  Connected! Your key is stored securely in Windows Credential Manager.
                </span>
              </div>
            )}

            {/* Standard Key Flow (Gemini, OpenRouter, OpenAI, Anthropic) */}
            {selectedProvider.id !== "ollama" ? (
              <div className="key-input-section">
                <label className="input-label" htmlFor="api-key-input">
                  Paste API Key:
                </label>
                <div className="key-input-wrapper">
                  <input
                    id="api-key-input"
                    data-testid="input-api-key"
                    type={showKey ? "text" : "password"}
                    className="key-input"
                    placeholder={selectedProvider.placeholder || "Paste your secret key here..."}
                    value={apiKey}
                    onChange={(e) => {
                      setApiKey(e.target.value);
                      if (errorMessage) setErrorMessage(null);
                    }}
                    disabled={isValidating || isSuccess}
                  />
                  <button
                    type="button"
                    className="btn-toggle-key"
                    onClick={() => setShowKey(!showKey)}
                    aria-label={showKey ? "Hide key" : "Show key"}
                  >
                    {showKey ? "Hide" : "Show"}
                  </button>
                </div>

                <div className="setup-footer">
                  <button
                    className="btn-primary"
                    onClick={handleTestAndSave}
                    disabled={!apiKey.trim() || isValidating || isSuccess}
                    data-testid="btn-test-save"
                  >
                    {isValidating ? "Validating Key..." : isSuccess ? "Saved!" : "Test & Save"}
                  </button>
                </div>
              </div>
            ) : (
              /* Ollama Auto-Detection Flow */
              <div className="ollama-section" data-testid="ollama-status">
                {isCheckingOllama ? (
                  <div className="ollama-status-box checking">
                    <span className="spinner" />
                    <span>Detecting local Ollama server at http://localhost:11434...</span>
                  </div>
                ) : ollamaDetected ? (
                  <div className="ollama-status-box detected">
                    <div className="detected-header">
                      <span className="status-dot-green" />
                      <strong>Ollama is running locally!</strong>
                    </div>
                    <div className="models-container">
                      <span className="models-label">Installed Models:</span>
                      {ollamaModels.length > 0 ? (
                        <div className="model-badges" data-testid="ollama-models">
                          {ollamaModels.map((m, idx) => (
                            <span key={idx} className="model-badge">
                              {m}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="no-models-hint">
                          No models pulled yet. You can run <code>ollama pull llama3.2</code> in your terminal.
                        </p>
                      )}
                    </div>
                    <div className="setup-footer">
                      <button
                        className="btn-primary"
                        onClick={handleOllamaFinish}
                        data-testid="btn-ollama-finish"
                      >
                        Connect & Save
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="ollama-status-box not-detected">
                    <p className="not-detected-msg">
                      Ollama was not detected at <code>http://localhost:11434</code>.
                    </p>
                    <div className="setup-footer">
                      <button
                        className="btn-secondary"
                        onClick={checkOllamaServer}
                        data-testid="btn-check-ollama"
                      >
                        Check again ⟳
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        .setup-wizard-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(10, 14, 23, 0.85);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 1000;
          padding: 20px;
          animation: fadeIn 0.2s ease-out;
        }

        .setup-wizard-card {
          width: 100%;
          max-width: 640px;
          background: #111827;
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 16px;
          box-shadow: 0 24px 48px rgba(0, 0, 0, 0.6), 0 0 24px rgba(59, 130, 246, 0.2);
          padding: 28px;
          color: #f3f4f6;
          display: flex;
          flex-direction: column;
          gap: 20px;
        }

        .setup-header {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          position: relative;
        }

        .btn-back {
          background: transparent;
          border: 1px solid rgba(255, 255, 255, 0.15);
          color: #9ca3af;
          border-radius: 8px;
          padding: 6px 12px;
          font-size: 0.85rem;
          cursor: pointer;
          transition: all 0.15s ease;
          align-self: flex-start;
        }

        .btn-back:hover {
          color: #fff;
          border-color: rgba(255, 255, 255, 0.3);
          background: rgba(255, 255, 255, 0.05);
        }

        .setup-title-group {
          flex: 1;
        }

        .setup-title {
          font-size: 1.35rem;
          font-weight: 700;
          color: #fff;
          margin-bottom: 4px;
        }

        .setup-subtitle {
          font-size: 0.88rem;
          color: #9ca3af;
          line-height: 1.4;
        }

        .btn-close {
          background: transparent;
          border: none;
          color: #9ca3af;
          font-size: 1.1rem;
          cursor: pointer;
          padding: 4px 8px;
        }

        .btn-close:hover {
          color: #fff;
        }

        /* Screen 1 Grid */
        .provider-grid {
          display: flex;
          flex-direction: column;
          gap: 10px;
          max-height: 380px;
          overflow-y: auto;
          padding-right: 4px;
        }

        .provider-card {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 14px 16px;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .provider-card:hover {
          background: rgba(255, 255, 255, 0.06);
          border-color: rgba(59, 130, 246, 0.4);
          transform: translateY(-1px);
        }

        .provider-card.selected {
          background: rgba(59, 130, 246, 0.1);
          border-color: #3b82f6;
          box-shadow: 0 0 16px rgba(59, 130, 246, 0.25);
        }

        .card-top {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }

        .provider-name-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .provider-name {
          font-weight: 600;
          font-size: 1rem;
          color: #fff;
        }

        .cost-badge {
          font-size: 0.68rem;
          font-weight: 700;
          padding: 2px 7px;
          border-radius: 6px;
          letter-spacing: 0.5px;
        }

        .badge-free {
          background: rgba(16, 185, 129, 0.18);
          color: #34d399;
          border: 1px solid rgba(16, 185, 129, 0.35);
        }

        .badge-paid {
          background: rgba(245, 158, 11, 0.18);
          color: #fbbf24;
          border: 1px solid rgba(245, 158, 11, 0.35);
        }

        .radio-indicator {
          width: 18px;
          height: 18px;
          border-radius: 50%;
          border: 2px solid rgba(255, 255, 255, 0.2);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .provider-card.selected .radio-indicator {
          border-color: #3b82f6;
        }

        .radio-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #3b82f6;
        }

        .provider-desc {
          font-size: 0.84rem;
          color: #9ca3af;
          line-height: 1.35;
        }

        /* Screen 2 Instructions */
        .instructions-box {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 14px 16px;
        }

        .instructions-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;
        }

        .inst-badge {
          font-size: 0.75rem;
          text-transform: uppercase;
          font-weight: 600;
          color: #3b82f6;
          letter-spacing: 0.5px;
        }

        .btn-external {
          background: rgba(59, 130, 246, 0.15);
          border: 1px solid rgba(59, 130, 246, 0.3);
          color: #60a5fa;
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 0.8rem;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .btn-external:hover {
          background: rgba(59, 130, 246, 0.25);
          color: #93c5fd;
        }

        .instructions-list {
          padding-left: 20px;
          font-size: 0.85rem;
          color: #d1d5db;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        /* Alerts */
        .alert-banner {
          display: flex;
          align-items: flex-start;
          gap: 10px;
          padding: 12px 14px;
          border-radius: 10px;
          font-size: 0.86rem;
          line-height: 1.4;
          animation: slideDown 0.18s ease-out;
        }

        .alert-error {
          background: rgba(239, 68, 68, 0.12);
          border: 1px solid rgba(239, 68, 68, 0.35);
          color: #fca5a5;
        }

        .alert-success {
          background: rgba(16, 185, 129, 0.12);
          border: 1px solid rgba(16, 185, 129, 0.35);
          color: #6ee7b7;
        }

        /* Key Input */
        .key-input-section {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .input-label {
          font-size: 0.85rem;
          font-weight: 600;
          color: #e5e7eb;
        }

        .key-input-wrapper {
          display: flex;
          align-items: center;
          background: rgba(0, 0, 0, 0.3);
          border: 1px solid rgba(255, 255, 255, 0.15);
          border-radius: 10px;
          overflow: hidden;
          transition: border-color 0.15s ease;
        }

        .key-input-wrapper:focus-within {
          border-color: #3b82f6;
          box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
        }

        .key-input {
          flex: 1;
          background: transparent;
          border: none;
          outline: none;
          color: #fff;
          font-size: 0.92rem;
          font-family: monospace;
          padding: 12px 14px;
        }

        .btn-toggle-key {
          background: transparent;
          border: none;
          color: #9ca3af;
          padding: 0 14px;
          font-size: 0.8rem;
          cursor: pointer;
        }

        .btn-toggle-key:hover {
          color: #fff;
        }

        /* Ollama Section */
        .ollama-status-box {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 12px;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .detected-header {
          display: flex;
          align-items: center;
          gap: 8px;
          color: #34d399;
        }

        .status-dot-green {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: #10b981;
          box-shadow: 0 0 8px #10b981;
        }

        .models-container {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .models-label {
          font-size: 0.82rem;
          color: #9ca3af;
        }

        .model-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .model-badge {
          background: rgba(59, 130, 246, 0.15);
          border: 1px solid rgba(59, 130, 246, 0.3);
          color: #93c5fd;
          padding: 3px 8px;
          border-radius: 6px;
          font-size: 0.8rem;
          font-family: monospace;
        }

        .no-models-hint {
          font-size: 0.84rem;
          color: #9ca3af;
        }

        .not-detected-msg {
          font-size: 0.88rem;
          color: #fca5a5;
        }

        /* Buttons & Footer */
        .setup-footer {
          display: flex;
          justify-content: flex-end;
          margin-top: 8px;
        }

        .btn-primary {
          background: #3b82f6;
          color: #fff;
          border: none;
          padding: 10px 22px;
          border-radius: 10px;
          font-weight: 600;
          font-size: 0.92rem;
          cursor: pointer;
          transition: all 0.15s ease;
          box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
        }

        .btn-primary:hover:not(:disabled) {
          background: #2563eb;
          box-shadow: 0 6px 16px rgba(59, 130, 246, 0.45);
          transform: translateY(-1px);
        }

        .btn-primary:disabled {
          opacity: 0.5;
          cursor: not-allowed;
          box-shadow: none;
        }

        .btn-secondary {
          background: rgba(255, 255, 255, 0.08);
          color: #e5e7eb;
          border: 1px solid rgba(255, 255, 255, 0.15);
          padding: 9px 18px;
          border-radius: 10px;
          font-size: 0.88rem;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .btn-secondary:hover {
          background: rgba(255, 255, 255, 0.15);
          color: #fff;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        @keyframes slideDown {
          from { opacity: 0; transform: translateY(-6px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
};

export default SetupWizard;
