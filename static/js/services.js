// Device Inventory — services.js
// Requires: SERVICES (global, from template), showToast() (from base.html)

// ── Formular-Hilfsfunktionen ──────────────────────────────────────────────────

function collectForm(prefix) {
    const kosten = document.getElementById(prefix + 'kosten').value;
    return {
        description:      document.getElementById(prefix + 'description').value.trim(),
        provider:         document.getElementById(prefix + 'provider').value.trim() || null,
        kategorie:        document.getElementById(prefix + 'kategorie').value,
        kosten:           kosten ? parseFloat(kosten) : null,
        kosten_intervall: document.getElementById(prefix + 'intervall').value,
        vertrag_beginn:   document.getElementById(prefix + 'vertrag-beginn').value || null,
        vertrag_ende:     document.getElementById(prefix + 'vertrag-ende').value || null,
        kuendigungsfrist: document.getElementById(prefix + 'kuendigungsfrist').value.trim() || null,
        avv_vorhanden:    document.getElementById(prefix + 'avv').checked,
        avv_date:        document.getElementById(prefix + 'avv-date').value || null,
        kontakt:          document.getElementById(prefix + 'kontakt').value.trim() || null,
        note:            document.getElementById(prefix + 'note').value.trim() || null,
    };
}

function showAddForm() {
    document.getElementById('addSection').style.display = 'block';
    document.getElementById('add-description').focus();
}

// ── Add ────────────────────────────────────────────────────────────────

document.getElementById('btnShowAdd').addEventListr('click', () => {
    const s = document.getElementById('addSection');
    if (s.style.display === 'none') { showAddForm(); } else { s.style.display = 'none'; }
});
document.getElementById('btnCancelAdd').addEventListr('click', () => {
    document.getElementById('addSection').style.display = 'none';
});
document.getElementById('btnEmptyAdd')?.addEventListr('click', showAddForm);

document.getElementById('btnSaveAdd').addEventListr('click', async function() {
    const payload = collectForm('add-');
    if (!payload.description) { showToast('Description is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/services', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Service saved.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── Edit ────────────────────────────────────────────────────────────────

function openEdit(id) {
    const s = SERVICES.find(x => x.id === id);
    if (!s) return;
    document.getElementById('edit-id').value            = s.id;
    document.getElementById('edit-description').value   = s.description || '';
    document.getElementById('edit-provider').value      = s.provider || '';
    document.getElementById('edit-kategorie').value     = s.kategorie || '';
    document.getElementById('edit-kosten').value        = s.kosten != null ? s.kosten : '';
    document.getElementById('edit-intervall').value     = s.kosten_intervall || 'monthly';
    document.getElementById('edit-vertrag-beginn').value = s.vertrag_beginn || '';
    document.getElementById('edit-vertrag-ende').value  = s.vertrag_ende || '';
    document.getElementById('edit-kuendigungsfrist').value = s.kuendigungsfrist || '';
    document.getElementById('edit-avv').checked         = !!s.avv_vorhanden;
    document.getElementById('edit-avv-date').value     = s.avv_date || '';
    document.getElementById('edit-kontakt').value       = s.kontakt || '';
    document.getElementById('edit-note').value         = s.note || '';
    document.getElementById('editDialog').showModal();
}

document.getElementById('btnCancelEdit').addEventListr('click', () => {
    document.getElementById('editDialog').close();
});

document.getElementById('btnSaveEdit').addEventListr('click', async function() {
    const id      = document.getElementById('edit-id').value;
    const payload = collectForm('edit-');
    if (!payload.description) { showToast('Description is required.', 'error'); return; }
    try {
        const resp = await fetch('/api/service/' + id, {
            method: 'PATCH',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showToast('Service updated.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
});

// ── Delete ───────────────────────────────────────────────────────────────────

async function confirmDelete(id) {
    const s = SERVICES.find(x => x.id === id);
    if (!confirm('Service "' + (s ? s.description : id) + '" really delete?')) return;
    try {
        const resp = await fetch('/api/service/' + id, {method: 'DELETE'});
        if (resp.ok) {
            showToast('Service deleted.', 'success');
            setTimeout(() => location.reload(), 800);
        } else {
            const data = await resp.json().catch(() => ({}));
            showToast('Error: ' + (data.detail || 'Unknown'), 'error');
        }
    } catch {
        showToast('Network error. Please check the connection.', 'error');
    }
}
