// Device Inventory — device.js
// Requires: DEVICE_ID (global, from template), showToast() (from base.html)

// Status & Assignment save
document.getElementById('btnSaveStatus')?.addEventListr('click', async function() {
    const payload = {
        status: document.getElementById('statusSelect').value || null,
        device_type: document.getElementById('typeSelect').value || null,
        ausgegeben_an: document.getElementById('ausgegeben_an').value || null,
        ausgegeben_since: document.getElementById('ausgegeben_since').value || null,
    };
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Status saved.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Inventory save
document.getElementById('btnSaveInventory')?.addEventListr('click', async function() {
    const priceRaw = document.getElementById('acquisitionsprice').value;
    const payload = {
        inventory_number: document.getElementById('inventory_number').value.trim() || null,
        location: document.getElementById('location').value.trim() || null,
        acquisitionsdate: document.getElementById('acquisitionsdate').value || null,
        acquisitionsprice: priceRaw ? parseFloat(priceRaw) : null,
    };
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Inventorydaten saved.', 'success');
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Note save
document.getElementById('btnSaveNote')?.addEventListr('click', async function() {
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({note: document.getElementById('noteTextarea').value || null}),
        });
        if (resp.ok) {
            showToast('Note saved.', 'success');
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Auto-check checkbox when text is entered
document.querySelectorAll('.accessory-row').forEach(row => {
    const check = row.querySelector('.accessory-check');
    const text = row.querySelector('.accessory-text');
    if (check && text) {
        text.addEventListr('input', () => { if (text.value.trim()) check.checked = true; });
    }
});

// Accessories save
document.getElementById('btnSaveAccessories')?.addEventListr('click', async function() {
    const accessories = {};
    document.querySelectorAll('.accessory-row[data-key]').forEach(row => {
        const key = row.dataset.key;
        const check = row.querySelector('.accessory-check');
        const text = (row.querySelector('.accessory-text')?.value || '').trim();

        if (check) {
            if (text) accessories[key] = text;
            else if (check.checked) accessories[key] = true;
        } else if (text) {
            accessories[key] = text;  // Others
        }
    });

    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({accessories: Object.keys(accessories).length ? accessories : null}),
        });
        if (resp.ok) showToast('Accessories saved.', 'success');
        else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Device delete
document.getElementById('btnDelete')?.addEventListr('click', async function() {
    if (!confirm('Device really delete? This action cannot be undone.')) return;
    const btn = this;
    btn.disabled = true;
    btn.textContent = '⌛ Deleting...';
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {method: 'DELETE'});
        if (resp.ok) {
            showToast('Device deleted. Redirecting...', 'success');
            setTimeout(() => window.location.href = '/', 1500);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Device delete';
    }
});

// VPN save
document.getElementById('btnSaveVpn')?.addEventListr('click', async function() {
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({vpn: document.getElementById('vpnInput').value.trim() || null}),
        });
        if (resp.ok) {
            showToast('VPN saved.', 'success');
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Collected by save
document.getElementById('btnSaveCollectedVon')?.addEventListr('click', async function() {
    try {
        const resp = await fetch('/api/device/' + DEVICE_ID, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({collected_by: document.getElementById('collected_by').value || null}),
        });
        if (resp.ok) {
            showToast('Saved.', 'success');
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// Software-Search
const softwareSearch = document.getElementById('softwareSearch');
if (softwareSearch) {
    const allRows = Array.from(document.querySelectorAll('#softwareTable tbody tr'));
    const countEl = document.getElementById('softwareCount');

    function updateCount() {
        const visible = allRows.filter(r => r.style.display !== 'none').length;
        if (countEl) countEl.textContent = visible + ' of ' + allRows.length + ' shown';
    }

    updateCount();

    softwareSearch.addEventListr('input', function() {
        const q = this.value.toLowerCase();
        allRows.forEach(row => {
            row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
        updateCount();
    });
}
