import React from "react";

/**
 * SetupWizard component for initial first-run onboarding:
 * 1. Selecting allowed directories (least privilege sandbox).
 * 2. Saving API key securely to Windows Credential Manager.
 */
export const SetupWizard: React.FC = () => {
  return (
    <div className="hud-container">
      <div className="hud-header">
        <div className="hud-title">Welcome to HeyBloopie Setup</div>
      </div>
      <div className="hud-body">
        <p style={{ marginBottom: "12px", color: "var(--text-secondary)" }}>
          HeyBloopie requires permission to manage files in specific folders.
        </p>
      </div>
    </div>
  );
};

export default SetupWizard;
