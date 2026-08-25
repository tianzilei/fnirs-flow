import { useMemo, useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Layers, Search, Sparkles } from 'lucide-react';
import { listAtomTemplates, type AtomTemplate } from '../api/client';
import {
  recommendationReasonForTemplate,
  recommendationTierForTemplate,
  type ChecklistTemplateRecommendation,
  type ChecklistRecommendationTier,
} from '../flow/atomFactory';

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

interface SidebarProps {
  highlightedTemplateIds?: string[];
  checklistRecommendations?: ChecklistTemplateRecommendation[];
  activeChecklistLabel?: string;
  dataBranch?: string;
}

const PROCESSED_HB_ALLOWED = new Set([
  'frozen_manifest_discovery', 'read_vendor_processed_hb', 'ingest_frozen_events',
  'regularize_processed_hb_time', 'compile_processed_hb_designs', 'fit_processed_hb_first_level',
  'estimate_full_contrasts', 'write_processed_hb_derivatives',
]);

const tierLabels: Record<ChecklistRecommendationTier, string> = {
  best: 'Best fit',
  recommended: 'Recommended',
  alternative: 'Alternative',
  off_path: 'Off path',
};

const tierRank: Record<ChecklistRecommendationTier, number> = {
  best: 0,
  recommended: 1,
  alternative: 2,
  off_path: 3,
};

export function Sidebar({
  highlightedTemplateIds = [],
  checklistRecommendations = [],
  activeChecklistLabel = '',
  dataBranch = '',
}: SidebarProps) {
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

  useEffect(() => {
    if (highlightedTemplateIds.length === 0) return;
    setActiveCategory('checklist');
    setExpanded(new Set(categoryOrder));
  }, [highlightedTemplateIds]);

  const categories = useMemo(() => {
    const seen = new Set(templates.map((template) => template.category));
    return categoryOrder.filter((category) => seen.has(category)).concat(
      [...seen].filter((category) => !categoryOrder.includes(category))
    );
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const highlighted = new Set(highlightedTemplateIds);
    return templates.filter((template) => {
      if (dataBranch === 'vendor_processed_hb' && !PROCESSED_HB_ALLOWED.has(template.operation || template.id)) return false;
      const highlightedTemplate = highlighted.has(template.id) || highlighted.has(template.operation);
      const inCategory = activeCategory === 'all' || template.category === activeCategory ||
        (activeCategory === 'checklist' && highlightedTemplate);
      const text = [
        template.display_name,
        template.atom_type,
        template.operation,
        template.description,
        template.category,
      ].join(' ').toLowerCase();
      return inCategory && (!normalizedQuery || text.includes(normalizedQuery));
    });
  }, [activeCategory, dataBranch, highlightedTemplateIds, query, templates]);

  const grouped = filteredTemplates.reduce<Record<string, AtomTemplate[]>>((acc, template) => {
    (acc[template.category] = acc[template.category] || []).push(template);
    return acc;
  }, {});
  Object.keys(grouped).forEach((category) => {
    grouped[category] = grouped[category].slice().sort((a, b) => {
      const aTier = recommendationTierForTemplate(checklistRecommendations, a);
      const bTier = recommendationTierForTemplate(checklistRecommendations, b);
      return tierRank[aTier] - tierRank[bTier] || a.display_name.localeCompare(b.display_name);
    });
  });

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

      {highlightedTemplateIds.length > 0 && (
        <button
          className="checklist-library-focus"
          onClick={() => {
            setActiveCategory('checklist');
            setExpanded(new Set(categoryOrder));
          }}
          type="button"
        >
          <Sparkles size={14} />
          <span>{activeChecklistLabel ? `Recommended for ${activeChecklistLabel}` : 'Checklist recommendations'}</span>
        </button>
      )}

      <div className="category-tabs" aria-label="Atom categories">
        <button className={activeCategory === 'all' ? 'active' : ''} onClick={() => setActiveCategory('all')}>
          All
        </button>
        {highlightedTemplateIds.length > 0 && (
          <button className={activeCategory === 'checklist' ? 'active' : ''} onClick={() => setActiveCategory('checklist')}>
            Checklist
          </button>
        )}
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
                    {atoms.map((atom) => {
                      const highlighted = highlightedTemplateIds.includes(atom.id) ||
                        highlightedTemplateIds.includes(atom.operation);
                      const tier = recommendationTierForTemplate(checklistRecommendations, atom);
                      const reason = highlighted ? recommendationReasonForTemplate(checklistRecommendations, atom) : '';
                      const showTier = highlighted && tier !== 'off_path';
                      return (
                      <div
                        key={atom.id}
                        className={`atom-item ${highlighted ? 'checklist-recommended' : ''} checklist-tier-${tier}`}
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
                        {showTier && <span className={`atom-recommendation tier-${tier}`}>{tierLabels[tier]}</span>}
                        {reason && <span className="atom-recommendation-reason">{reason}</span>}
                      </div>
                      );
                    })}
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
