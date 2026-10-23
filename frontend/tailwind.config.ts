// Tailwind 扫描路径与主题配置：只为扫描到的类生成样式；颜色语义统一供页面与组件复用。
// 视觉基线采用 Apple 风格：系统字体栈、近黑正文、浅灰面板、Apple 蓝强调色与更柔和的圆角/阴影。
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#1d1d1f",
        panel: "#f5f5f7",
        line: "#d2d2d7",
        accent: "#0071e3",
        warn: "#bf4800",
        // Apple 中性灰阶，统一替换项目里大量使用的 slate 语义色。
        slate: {
          50: "#f5f5f7",
          100: "#e8e8ed",
          200: "#d2d2d7",
          300: "#c7c7cc",
          400: "#a1a1a6",
          500: "#6e6e73",
          600: "#515154",
          700: "#3a3a3c",
          800: "#2c2c2e",
          900: "#1d1d1f",
          950: "#000000"
        },
        // 项目原有 teal 强调色整体映射为 Apple 蓝，避免逐页改类名。
        teal: {
          50: "#eef6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#0071e3",
          600: "#0066cc",
          700: "#005bb5",
          800: "#004a99",
          900: "#003b7a",
          950: "#002b59"
        },
        apple: {
          blue: "#0071e3",
          blueHover: "#0077ed",
          ink: "#1d1d1f",
          secondary: "#6e6e73",
          tertiary: "#86868b",
          surface: "#f5f5f7",
          green: "#34c759",
          red: "#ff3b30",
          orange: "#ff9f0a",
          yellow: "#ffd60a",
          purple: "#bf5af2",
          pink: "#ff2d55"
        }
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "SF Pro Display",
          "SF Pro Text",
          "Helvetica Neue",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "Arial",
          "sans-serif"
        ],
        mono: ["SFMono-Regular", "SF Mono", "Menlo", "Monaco", "Consolas", "Liberation Mono", "monospace"]
      },
      borderRadius: {
        sm: "0.5rem",
        DEFAULT: "0.75rem",
        md: "0.75rem",
        lg: "1rem",
        xl: "1.25rem",
        "2xl": "1.5rem",
        "3xl": "2rem"
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0,0,0,0.04), 0 1px 3px rgba(0,0,0,0.03)",
        DEFAULT: "0 2px 8px rgba(0,0,0,0.04), 0 12px 32px rgba(0,0,0,0.05)",
        md: "0 4px 16px rgba(0,0,0,0.06), 0 16px 40px rgba(0,0,0,0.06)",
        lg: "0 8px 30px rgba(0,0,0,0.08), 0 2px 8px rgba(0,0,0,0.04)",
        xl: "0 20px 60px rgba(0,0,0,0.12)"
      },
      letterSpacing: {
        tightest: "-0.04em"
      },
      transitionTimingFunction: {
        apple: "cubic-bezier(0.25, 0.1, 0.25, 1)"
      }
    }
  },
  plugins: []
};

export default config;
