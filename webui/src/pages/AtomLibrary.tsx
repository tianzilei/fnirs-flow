import { useMemo, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layers,
  Search,
  Sparkles,
  ArrowRight,
  CircleDot,
  Database,
  FlaskConical,
  Gauge,
  Activity,
  FileOutput,
  ShieldCheck,
  Braces,
} from 'lucide-react';
import { listAtomTemplates, type AtomTemplate } from '../api/client';

const categoryColors: Record<string, string> = {
  data: '#0f766e',
  design: '#2563eb',
  preprocessing: '#b45309',
  analysis: '#7c3aed',
  output: '#0284c7',
  validation: '#dc2626',
  export: '#57534e',
};

const categoryIcons: Record<string, typeof Database> = {
  data: Database,
  design: FlaskConical,
  preprocessing: Gauge,
  analysis: Activity,
  output: FileOutput,
  validation: ShieldCheck,
  export: Braces,
};

const categoryOrder = ['data', 'design', 'preprocessing', 'analysis', 'output', 'validation', 'export'];

export function AtomLibrary() {
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<AtomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');
  const [selectedAtom, setSelectedAtom] = useState<AtomTemplate | null>(null);

  useEffect(() => {
    listAtomTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const seen = new Set(templates.map((t) => t.category));
    return categoryOrder.filter((c) => seen.has(c)).concat(
      [...seen].filter((c) => !categoryOrder.includes(c))
    );
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return templates.filter((t) => {
      const inCategory = activeCategory === 'all' || t.category === activeCategory;
      const text = [t.display_name, t.atom_type, t.operation, t.description, t.category].join(' ').toLowerCase();
      return inCategory && (!normalizedQuery || text.includes(normalizedQuery));
    });
  }, [activeCategory, query, templates]);

  return (
    <div className="page atom-library-page work-page">
      <section className="page-header">
        <div>
          <span className="page-kicker">Library</span>
          <h2>Method Atom Templates</h2>
        </div>
        <span className="template-count">{templates.length} templates</span>
      </section>

      <div className="atom-library-layout">
        <div className="atom-library-list">
          <label className="search-field">
            <Search size={15} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search atoms by name, type, operation, description..."
              type="search"
            />
          </label>

          <div className="category-tabs" aria-label="Atom categories">
            <button className={activeCategory === 'all' ? 'active' : ''} onClick={() => setActiveCategory('all')}>
              All
            </button>
            {categories.map((category) => (
              <button
                key={category}
                className={activeCategory === category ? 'active' : ''}
                onClick={() => setActiveCategory(category)}
              >
                {category}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="sidebar-loading">
              <Sparkles size={16} />
              <span>Loading templates...</span>
            </div>
          ) : (
            <div className="atom-library-items">
              {filteredTemplates.map((atom) => {
                const Icon = categoryIcons[atom.category] || CircleDot;
                return (
                  <div
                    key={atom.id}
                    className={`atom-library-item ${selectedAtom?.id === atom.id ? 'selected' : ''}`}
                    onClick={() => setSelectedAtom(atom)}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData('application/atom-template', JSON.stringify(atom));
                      event.dataTransfer.effectAllowed = 'copy';
                    }}
                  >
                    <span className="atom-icon" style={{ color: categoryColors[atom.category] || '#525252' }}>
                      <Icon size={16} />
                    </span>
                    <div className="atom-info">
                      <span className="atom-name">{atom.display_name || atom.atom_type}</span>
                      <span className="atom-operation">{atom.operation || atom.atom_type}</span>
                    </div>
                    <span className="atom-category-badge" style={{ borderColor: categoryColors[atom.category] || '#94a3b8' }}>
                      {atom.category}
                    </span>
                    {atom.evidence_refs.length > 0 && (
                      <span className="atom-evidence" title={`${atom.evidence_refs.length} evidence refs`}>
                        E{atom.evidence_refs.length}
                      </span>
                    )}
                  </div>
                );
              })}

              {filteredTemplates.length === 0 && (
                <div className="empty-state compact">
                  <p>No matching atoms.</p>
                </div>
              )}
            </div>
          )}
        </div>

        <aside className="atom-detail-panel">
          {selectedAtom ? (
            <>
              <div className="atom-detail-header">
                <span className="atom-detail-category" style={{ color: categoryColors[selectedAtom.category] || '#525252' }}>
                  {selectedAtom.category}
                </span>
                <h3>{selectedAtom.display_name || selectedAtom.atom_type}</h3>
                <p className="atom-detail-type">{selectedAtom.atom_type}</p>
              </div>

              <div className="atom-detail-section">
                <h4>Operation</h4>
                <p>{selectedAtom.operation || '-'}</p>
              </div>

              {selectedAtom.description && (
                <div className="atom-detail-section">
                  <h4>Description</h4>
                  <p>{selectedAtom.description}</p>
                </div>
              )}

              {selectedAtom.input_ports.length > 0 && (
                <div className="atom-detail-section">
                  <h4>Input Ports</h4>
                  {selectedAtom.input_ports.map((port) => (
                    <div key={port.name} className="port-row">
                      <span className="port-dot in" />
                      <span>{port.name}</span>
                      <code>{port.schema}</code>
                      {port.required && <span className="port-required">required</span>}
                    </div>
                  ))}
                </div>
              )}

              {selectedAtom.output_ports.length > 0 && (
                <div className="atom-detail-section">
                  <h4>Output Ports</h4>
                  {selectedAtom.output_ports.map((port) => (
                    <div key={port.name} className="port-row">
                      <span className="port-dot out" />
                      <span>{port.name}</span>
                      <code>{port.schema}</code>
                    </div>
                  ))}
                </div>
              )}

              {selectedAtom.evidence_refs.length > 0 && (
                <div className="atom-detail-section">
                  <h4>Evidence References ({selectedAtom.evidence_refs.length})</h4>
                  <ul className="evidence-list">
                    {selectedAtom.evidence_refs.map((ref, i) => (
                      <li key={i}>{ref}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="atom-detail-actions">
                <button className="primary-button" onClick={() => navigate(-1)}>
                  <ArrowRight size={14} />
                  Back to Flow
                </button>
              </div>
            </>
          ) : (
            <div className="atom-detail-empty">
              <Layers size={32} />
              <p>Select an atom to view details</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
