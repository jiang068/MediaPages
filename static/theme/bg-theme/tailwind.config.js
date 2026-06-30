/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./*.html", "./*.js"], // 扫描你所有的 HTML 和 JS 文件
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        classic: {
          gold: '#dfb76c',
          green: '#2c4a3e',
          dark: '#121614',
          light: '#f7f6f2'
        }
      }
    },
  },
  plugins: [],
}