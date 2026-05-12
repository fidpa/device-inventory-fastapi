# Configure WebDAV

The application can sync data from any WebDAV-compatible server. This guide shows how to configure it for the most common providers.

## How the import works

1. End-user collectors (`sysinfo/win/collect-sysinfo.ps1`, `sysinfo/mac/collect-sysinfo.py`, etc.) write a JSON file and upload it via HTTP `PUT` to a configured WebDAV inbox.
2. `scripts/import_sysinfo.py` runs on a systemd timer, lists the inbox via `PROPFIND`, downloads new files, parses them, and writes rows into SQLite.
3. After successful import, the JSON files remain in the WebDAV inbox until you delete them through the admin UI.

## Required environment variables

In `.env`:

```ini
NEXTCLOUD_URL=https://cloud.example.com
NEXTCLOUD_USER=sysinfo
NEXTCLOUD_PASSWORD=<app-password>
NEXTCLOUD_PATH=/remote.php/dav/files/sysinfo/inbox
```

> The variable names are historical — they work with any WebDAV provider, not just Nextcloud.

## Provider-specific setup

### Nextcloud

1. Create a dedicated user `sysinfo` (or reuse an existing one).
2. Settings → Security → "Devices & sessions" → **Create new app password** named `device-inventory`.
3. Use that app password as `NEXTCLOUD_PASSWORD`.
4. Path format: `/remote.php/dav/files/<USER>/<FOLDER>`

```ini
NEXTCLOUD_URL=https://cloud.example.com
NEXTCLOUD_USER=sysinfo
NEXTCLOUD_PASSWORD=xxxx-xxxx-xxxx-xxxx-xxxx
NEXTCLOUD_PATH=/remote.php/dav/files/sysinfo/inbox
```

### ownCloud

Same as Nextcloud — both use the same WebDAV path format.

### Seafile

Seafile's WebDAV is at a different URL prefix. Adjust `NEXTCLOUD_PATH` accordingly:

```ini
NEXTCLOUD_URL=https://seafile.example.com
NEXTCLOUD_USER=sysinfo@example.com
NEXTCLOUD_PASSWORD=<password>
NEXTCLOUD_PATH=/seafdav/inventory-library
```

### Apache mod_dav

A self-hosted Apache server with `mod_dav` enabled:

```apache
<Location /webdav>
  DAV On
  AuthType Basic
  AuthName "Inventory Inbox"
  AuthUserFile /etc/apache2/webdav.htpasswd
  Require valid-user
</Location>
```

```ini
NEXTCLOUD_URL=https://files.example.com
NEXTCLOUD_USER=sysinfo
NEXTCLOUD_PASSWORD=<htpasswd-password>
NEXTCLOUD_PATH=/webdav/inbox
```

## Testing the connection

A quick sanity check from the server:

```bash
# List the inbox
curl -u "$NEXTCLOUD_USER:$NEXTCLOUD_PASSWORD" \
  -X PROPFIND \
  -H "Depth: 1" \
  "$NEXTCLOUD_URL$NEXTCLOUD_PATH/"

# Should return 207 Multi-Status with an XML listing
```

If you get `401`, your credentials are wrong. If you get `404`, the path is wrong.

## Security notes

- **Never commit `.env`** — it contains credentials. The provided `.gitignore` already excludes it.
- **Use an app-specific password**, never the user's real login password. App passwords can be revoked individually if compromised.
- **Restrict the inbox account's permissions** to the inbox folder only. The collector should not have access to other folders.
- **Rotate the app password** if you suspect it has leaked. Generate a new one, update `.env`, restart the service.

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | Wrong credentials | Verify with `curl` (see above) |
| `404 Not Found` | Wrong `NEXTCLOUD_PATH` | Check the leading slash, the user folder, and the inbox folder name |
| `405 Method Not Allowed` | Server doesn't speak WebDAV | Confirm the `<Dav>` capability in the server's response headers |
| `Connection refused` | Firewall or wrong port | Check `iptables` / cloud firewall rules |
| TLS errors | Self-signed certificate | Add CA cert or use a properly signed cert (recommended) |
