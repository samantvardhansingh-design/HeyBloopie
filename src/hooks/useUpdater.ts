import { useState } from 'react';
import { check } from '@tauri-apps/plugin-updater';
import { relaunch } from '@tauri-apps/plugin-process';

export function useUpdater() {
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [progress, setProgress] = useState<number>(0);
  const [statusMessage, setStatusMessage] = useState<string>('');

  const checkForUpdates = async () => {
    try {
      const update = await check();
      if (!update) {
        setStatusMessage('HeyBloopie is up to date.');
        return;
      }

      setIsUpdating(true);
      setStatusMessage(`A new version (${update.version}) is available. Updating...`);

      let totalBytes = 0;
      let downloadedBytes = 0;

      await update.downloadAndInstall((event) => {
        switch (event.event) {
          case 'Started':
            totalBytes = event.data.contentLength || 0;
            setProgress(0);
            setStatusMessage('Download started...');
            break;
          case 'Progress':
            downloadedBytes += event.data.chunkLength;
            if (totalBytes > 0) {
              const pct = Math.round((downloadedBytes / totalBytes) * 100);
              setProgress(pct);
              setStatusMessage(`Downloading update: ${pct}%`);
            } else {
              setStatusMessage(`Downloading update: ${(downloadedBytes / (1024 * 1024)).toFixed(1)} MB`);
            }
            break;
          case 'Finished':
            setProgress(100);
            setStatusMessage('Update complete. Relaunching...');
            break;
        }
      });

      // Relaunch the app to apply the update
      await relaunch();
    } catch (error) {
      console.error('Update failed:', error);
      setStatusMessage('Update check encountered an error.');
      setIsUpdating(false);
    }
  };

  return { checkForUpdates, isUpdating, progress, statusMessage };
}
