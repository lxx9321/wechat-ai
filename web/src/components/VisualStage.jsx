import visualStageImage from "../assets/visual-stage-direction-2.5.png";

export function VisualStage() {
  return (
    <aside className="visual-stage" aria-label="视觉内容区域">
      <img
        src={visualStageImage}
        alt="深色建筑空间中透出一束克制的琥珀色光线"
        draggable="false"
      />
    </aside>
  );
}

