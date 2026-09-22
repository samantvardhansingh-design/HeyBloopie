import React, { useState } from "react";
import Overlay from "./components/Overlay";
import SetupWizard from "./components/SetupWizard";

export const App: React.FC = () => {
  const [isConfigured] = useState<boolean>(true);

  return (
    <main style={{ width: "100%", height: "100%" }}>
      {isConfigured ? <Overlay /> : <SetupWizard />}
    </main>
  );
};

export default App;
