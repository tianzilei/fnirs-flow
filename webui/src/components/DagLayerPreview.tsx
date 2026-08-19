import { GitBranch, ArrowRight } from 'lucide-react';

interface DagNode {
  id: string;
  atom_type?: string;
  operation?: string;
}

interface DagLayerPreviewProps {
  layers?: DagNode[][];
  nodes?: DagNode[];
}

export function DagLayerPreview({ layers, nodes }: DagLayerPreviewProps) {
  if (!layers && !nodes) {
    return (
      <div className="dag-layer-preview empty">
        <p className="muted">No DAG data available. Compile the flow to generate the execution DAG.</p>
      </div>
    );
  }

  const layerData = layers || groupNodesByLayer(nodes || []);

  if (layerData.length === 0) {
    return (
      <div className="dag-layer-preview empty">
        <p className="muted">No execution layers found.</p>
      </div>
    );
  }

  return (
    <div className="dag-layer-preview">
      <div className="dag-header">
        <GitBranch size={16} />
        <span>Execution DAG: {layerData.length} layers</span>
      </div>
      <div className="dag-layers">
        {layerData.map((layer, layerIndex) => (
          <div key={layerIndex} className="dag-layer">
            <div className="layer-label">
              <span className="layer-number">L{layerIndex + 1}</span>
              <span className="layer-count">{layer.length} node{layer.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="layer-nodes">
              {layer.map((node, nodeIndex) => (
                <div key={node.id || nodeIndex} className="dag-node">
                  <code className="node-id">{node.id}</code>
                  {node.atom_type && (
                    <span className="node-type">{node.atom_type}</span>
                  )}
                </div>
              ))}
            </div>
            {layerIndex < layerData.length - 1 && (
              <div className="layer-arrow">
                <ArrowRight size={14} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function groupNodesByLayer(nodes: DagNode[]): DagNode[][] {
  if (nodes.length === 0) return [];
  return [nodes];
}
