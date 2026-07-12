import { useMemo, useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Layers, Search, Sparkles } from 'lucide-react';
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

const categoryOrder = ['data', 'design', 'preprocessing', 'analysis', 'output', 'validation', 'export'];

export function Sidebar() {
  const [templates, setTemplates] = useState<AtomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(categoryOrder));
  const [query, setQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState('all');

  useEffect(() => {
    listAtomTemplates()
      .then(setTemplates)
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const seen = new Set(templates.map((template) => template.category));
    return categoryOrder.filter((category) => seen.has(category)).concat(
      [...seen].filter((category) => !categoryOrder.includes(category))
    );
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return templates.filter((template) => {
      const inCategory = activeCategory === 'all' || template.category === activeCategory;
      const text = [
        template.display_name,
        template.atom_type,
        template.operation,
        template.description,
        template.category,
      ].join(' ').toLowerCase();
      return inCategory && (!normalizedQuery || text.includes(normalizedQuery));
    });
  }, [activeCategory, query, templates]);

  const grouped = filteredTemplates.reduce<Record<string, AtomTemplate[]>>((acc, template) => {
    (acc[template.category] = acc[template.category] || []).push(template);
    return acc;
  }, {});

  const toggleCategory = (category: string) => {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const onDragStart = (event: React.DragEvent, template: AtomTemplate) => {
    event.dataTransfer.setData('application/atom-template', JSON.stringify(template));
    event.dataTransfer.effectAllowed = 'copy';
  };

  return (
    <aside className="sidebar flow-library">
      <div className="sidebar-header">
        <div>
          <span className="sidebar-kicker">Library</span>
          <h3>Method Atoms</h3>
        </div>
        <span className="sidebar-count">{templates.length}</span>
      </div>

      <label className="search-field">
        <Search size={15} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search atoms"
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
        <div className="atom-groups">
          {Object.entries(grouped).map(([category, atoms]) => {
            const open = expanded.has(category);
            return (
              <section key={category} className="atom-category">
                <button className="category-header" onClick={() => toggleCategory(category)}>
                  <span className="category-color" style={{ backgroundColor: categoryColors[category] || '#64748b' }} />
                  <span>{category}</span>
                  <span className="category-size">{atoms.length}</span>
                  {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                </button>
                {open && (
                  <div className="category-atoms">
                    {atoms.map((atom) => (
                      <div
                        key={atom.id}
                        className="atom-item"
                        draggable
                        onDragStart={(event) => onDragStart(event, atom)}
                        title={atom.description || atom.atom_type}
                      >
                        <Layers size={15} />
                        <div className="atom-copy">
                          <span className="atom-name">{atom.display_name || atom.atom_type}</span>
                          <span className="atom-operation">{atom.operation || atom.atom_type}</span>
                        </div>
                        {atom.evidence_refs.length > 0 && (
                          <span className="atom-evidence" title={`${atom.evidence_refs.length} evidence refs`}>
                            E{atom.evidence_refs.length}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}

          {filteredTemplates.length === 0 && (
            <div className="empty-state compact">
              <p>No matching atoms.</p>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
