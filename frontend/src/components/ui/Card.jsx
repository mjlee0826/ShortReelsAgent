import React from 'react';

/**
 * Card：表面層容器（卡片 / 面板）。
 * interactive 為 true 時加上 hover 邊框、陰影與游標，供可點擊的卡片使用。
 */
export default function Card({ interactive = false, className = '', children, ...rest }) {
  return (
    <div
      className={[
        'bg-surface border border-border rounded-2xl',
        interactive
          ? 'cursor-pointer transition-all hover:border-accent/60 hover:shadow-lg hover:shadow-accent/5'
          : '',
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </div>
  );
}
