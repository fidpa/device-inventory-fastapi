// Device Inventory — ctr.js
// Requires: CTR_HOSTS (global, from template), showToast() (from base.html)

// Flache VM-Lookup-Map aufbauen
const CTR_VMS = {};
for (const host of CTR_HOSTS) {
    for (const vm of host.vms || []) {
        CTR_VMS[vm.id] = vm;
    }
}

// ── Host add ───────────────────────────────────────────────────────────

document.getElementById('btnShowAddHost').addEventListr('click', () => {
    const s = document.getElementById('addHostSection');
    const visible = s.style.display !== 'none';
    s.style.display = visible ? 'none' : 'block';
    if (!visible) document.getElementById('add-host-hostname').focus();
});

document.getElementById('btnCancelAddHost').addEventListr('click', () => {
    document.getElementById('addHostSection').style.display = 'none';
});

document.getElementById('btnSaveAddHost').addEventListr('click', async () => {
    const payload = {
        hostname:      document.getElementById('add-host-hostname').value.trim(),
        operating_system: document.getElementById('add-host-bs').value.trim() || null,
        cpu:           document.getElementById('add-host-cpu').value.trim() || null,
        storage:      document.getElementById('add-host-storage').value.trim() || null,
        ram:           document.getElementById('add-host-ram').value.trim() || null,
        manufacturer_sn: document.getElementById('add-host-sn').value.trim() || null,
    };
    if (!payload.hostname) { showToast('Hostname is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/ctr/hosts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Host saved.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── Host edit ───────────────────────────────────────────────────────────

function openEditHost(id) {
    const host = CTR_HOSTS.find(h => h.id === id);
    if (!host) return;
    document.getElementById('edit-host-id').value       = host.id;
    document.getElementById('edit-host-hostname').value = host.hostname || '';
    document.getElementById('edit-host-bs').value       = host.operating_system || '';
    document.getElementById('edit-host-cpu').value      = host.cpu || '';
    document.getElementById('edit-host-storage').value = host.storage || '';
    document.getElementById('edit-host-ram').value      = host.ram || '';
    document.getElementById('edit-host-sn').value       = host.manufacturer_sn || '';
    document.getElementById('editHostDialog').showModal();
}

document.getElementById('btnCancelEditHost').addEventListr('click', () => {
    document.getElementById('editHostDialog').close();
});

document.getElementById('btnDeleteHost').addEventListr('click', () => {
    const id   = document.getElementById('edit-host-id').value;
    const host = CTR_HOSTS.find(h => h.id === Number(id));
    document.getElementById('editHostDialog').close();
    confirmDeleteHost(id, host ? host.hostname : id);
});

document.getElementById('btnSaveEditHost').addEventListr('click', async () => {
    const id = document.getElementById('edit-host-id').value;
    const payload = {
        hostname:      document.getElementById('edit-host-hostname').value.trim(),
        operating_system: document.getElementById('edit-host-bs').value.trim() || null,
        cpu:           document.getElementById('edit-host-cpu').value.trim() || null,
        storage:      document.getElementById('edit-host-storage').value.trim() || null,
        ram:           document.getElementById('edit-host-ram').value.trim() || null,
        manufacturer_sn: document.getElementById('edit-host-sn').value.trim() || null,
    };
    if (!payload.hostname) { showToast('Hostname is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/ctr/host/' + id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Host updated.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── Host delete ──────────────────────────────────────────────────────────────

async function confirmDeleteHost(id, name) {
    if (!confirm('Really delete host "' + name + '" and all related VMs?')) return;
    try {
        const resp = await fetch('/api/ctr/host/' + id, {method: 'DELETE'});
        if (resp.ok) {
            showToast('Host deleted.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
}

// ── VM add ─────────────────────────────────────────────────────────────

function openAddVm(hostId) {
    document.getElementById('add-vm-host-id').value = hostId;
    document.getElementById('add-vm-name').value = '';
    document.getElementById('add-vm-os').value = '';
    document.getElementById('add-vm-vram').value = '';
    document.getElementById('add-vm-vcpus').value = '';
    document.getElementById('add-vm-verwendung').value = '';
    document.getElementById('addVmDialog').showModal();
    document.getElementById('add-vm-name').focus();
}

document.getElementById('btnCancelAddVm').addEventListr('click', () => {
    document.getElementById('addVmDialog').close();
});

document.getElementById('btnSaveAddVm').addEventListr('click', async () => {
    const hostId = document.getElementById('add-vm-host-id').value;
    const payload = {
        name:       document.getElementById('add-vm-name').value.trim(),
        os:         document.getElementById('add-vm-os').value.trim() || null,
        vram:       document.getElementById('add-vm-vram').value.trim() || null,
        vcpus:      document.getElementById('add-vm-vcpus').value.trim() || null,
        verwendung: document.getElementById('add-vm-verwendung').value.trim() || null,
    };
    if (!payload.name) { showToast('VM name is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/ctr/host/' + hostId + '/vms', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('VM saved.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── VM edit ─────────────────────────────────────────────────────────────

function openEditVm(id) {
    const vm = CTR_VMS[id];
    if (!vm) return;
    document.getElementById('edit-vm-id').value         = vm.id;
    document.getElementById('edit-vm-name').value       = vm.name || '';
    document.getElementById('edit-vm-os').value         = vm.os || '';
    document.getElementById('edit-vm-vram').value       = vm.vram || '';
    document.getElementById('edit-vm-vcpus').value      = vm.vcpus || '';
    document.getElementById('edit-vm-verwendung').value = vm.verwendung || '';
    document.getElementById('editVmDialog').showModal();
}

document.getElementById('btnCancelEditVm').addEventListr('click', () => {
    document.getElementById('editVmDialog').close();
});

document.getElementById('btnDeleteVm').addEventListr('click', () => {
    const id = document.getElementById('edit-vm-id').value;
    const vm = CTR_VMS[Number(id)];
    document.getElementById('editVmDialog').close();
    confirmDeleteVm(id, vm ? vm.name : id);
});

document.getElementById('btnSaveEditVm').addEventListr('click', async () => {
    const id = document.getElementById('edit-vm-id').value;
    const payload = {
        name:       document.getElementById('edit-vm-name').value.trim(),
        os:         document.getElementById('edit-vm-os').value.trim() || null,
        vram:       document.getElementById('edit-vm-vram').value.trim() || null,
        vcpus:      document.getElementById('edit-vm-vcpus').value.trim() || null,
        verwendung: document.getElementById('edit-vm-verwendung').value.trim() || null,
    };
    if (!payload.name) { showToast('VM name is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/ctr/vm/' + id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('VM updated.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── VM delete ────────────────────────────────────────────────────────────────

async function confirmDeleteVm(id, name) {
    if (!confirm('VM "' + name + '" really delete?')) return;
    try {
        const resp = await fetch('/api/ctr/vm/' + id, {method: 'DELETE'});
        if (resp.ok) {
            showToast('VM deleted.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
}
