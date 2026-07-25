import * as React from "react";

export function Button({className = "", ...props}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`} {...props} />;
}

