# Privacy Policy (Drive Opener)

[日本語](PRIVACY.md) | English

Last updated: November 22, 2026

This page explains what information the Chrome extension "Drive Opener" (the "extension") and the program you install on your computer, the "Drive Opener host app" (the "host app"), handle and how.

## Summary

- The extension and the host app **do not send your information anywhere**. They never send information to the developer's servers or to any third party, and they do not connect to the internet
- They do not ask you to sign in to your Google Account or to grant access to your Google Drive
- Your information is never sold, used for advertising, or shared with third parties

## Information the extension handles

On Google Drive pages (`https://drive.google.com/`), the extension reads:

- The URL of the page you are viewing (to know which folder is open)
- The ID of the selected or right-clicked item (to know what to open)

It only passes these to the host app installed on the same computer and never sends them anywhere else. The extension does not store them.

The only thing the extension stores on your computer (in Chrome's storage for extensions) is whether you have opened its options page, so that the keyboard shortcut tip is shown only once.

When you use "Copy local path", the extension writes the folder's location on your computer (for example `G:\My Drive\...`) to the clipboard. It never reads the clipboard.

## Information the host app handles

Using the item ID it receives from the extension, the host app finds the folder's location on your computer and opens it in Windows File Explorer.

- To find the location, it reads the database that Google Drive for desktop keeps on your computer (`%LOCALAPPDATA%\Google\DriveFS\...\metadata_sqlite_db`) in **read-only** mode. It never changes it
- It checks that the folder exists on the Google Drive for desktop drive (for example `G:\`)
- Only when an unexpected error occurs, it writes the error to `%LOCALAPPDATA%\DriveOpener\host.log`. This file stays on your computer and is never sent anywhere. It is deleted when you uninstall the host app

The host app does not connect to the internet.

## Sharing with third parties

The extension and the host app do not share or sell information to any third party.

## Contact

If you have questions, please open an issue in the GitHub repository (https://github.com/rgold2xxx-dotcom/drive-opener).

## Changes

If this policy changes, this page will be updated and the "Last updated" date above will change.
