import React from 'react';
import ProjectCard from './ProjectCard';

/**
 * ProjectGrid：專案卡片網格（Composite）。
 *
 * 把每個 ProjectMeta 渲染成一張 ProjectCard，回呼全數透傳給父頁，本身不持狀態。
 * 以 auto-rows-fr + 響應式欄數（1 / 2 / 3）保證同列卡片等高。
 */
export default function ProjectGrid({ projects, onOpen, onManage, onDelete, onSync }) {
  return (
    <div className="grid auto-rows-fr grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
      {projects.map((project) => (
        <ProjectCard
          key={project.name}
          project={project}
          onOpen={onOpen}
          onManage={onManage}
          onDelete={onDelete}
          onSync={onSync}
        />
      ))}
    </div>
  );
}
