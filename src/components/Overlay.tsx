import React from "react";

interface OverlayProps {
  onClose?: () => void;
}

/**
 * Overlay component that appears when global hotkey (Ctrl+Shift+Space) is pressed.
 * Handles voice interaction and text commands for desktop file actions.
 */
export const Overlay: React.FC<OverlayProps> = ({ onClose }) => {
  return (
    <div className="hud-container">
      <div className="hud-header">
        <div className="hud-title">
          <span className="hud-status-dot"></span>
          HeyBloopie
        </div>
        <button className="hud-btn" style={{ background: "transparent", color: "#9ca3af" }} onClick={onClose}>
          Esc
        </button>
      </div>

      <div className="hud-body">
        <p style={{ color: "var(--text-secondary)", fontSize: "0.95rem" }}>
          Press and speak, or type a request to manage your files...
        </p>
      </div>

      <div className="hud-input-bar">
        <input type="text" placeholder="e.g. Find all receipts from last month in Downloads" />
        <button className="hud-btn">Ask</button>
      </div>
    </div>
  );
};

export default Overlay;
