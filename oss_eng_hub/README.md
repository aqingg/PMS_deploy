# OSS_ENG_HUB

OSS_ENG_HUB 是一个工具入口门户。首页展示工具列表，点击后通过 iframe 加载各个独立工具页面。

当前门户本身有两个固定约束：

- 门户部署路径使用 `/oss_eng_hub/`
- 门户自身使用 `HashRouter`
- 新增工具如果自身是 SPA，内部路由必须使用 `HashRouter`

说明：门户使用 hash 路由后，不再给 React Router 单独配置 `basename`。部署前缀由 Vite 的 `base: '/oss_eng_hub/'` 负责，开发环境访问 `/`，生产环境访问 `/oss_eng_hub/`。

## 本地启动

```bash
npm install
npm run dev
```

默认构建命令：

```bash
npm run build
```

## 现有接入方式

门户壳工程负责：

- 首页和侧边栏入口
- 根据 `src/custom/tools.js` 生成工具入口
- 通过 `iframe` 加载 `public/<toolPath>/index.html`

新增工具时，需要同时处理两部分：

1. 把工具产物放到 `public` 目录下
2. 在门户配置里注册工具入口

## 如何添加新的项目

假设新增项目名为 `my_tool`。

### 1. 准备工具静态资源

将新项目编译后的静态资源放到：

```text
public/my_tool/
```

并确保入口文件存在：

```text
public/my_tool/index.html
```

门户会按下面的规则拼接 iframe 地址：

```text
/oss_eng_hub/my_tool/index.html
```

因此最终产物必须能通过这个地址正常访问。

### 2. 注册门户入口

在 `src/custom/tools.js` 中新增一个工具项，例如：

```js
export const toolItems = [
	{
		key: 'home',
		title: '首页',
		desc: '工具总览与快速入口。',
		path: '/',
		icon: 'pi pi-home'
	},
	{
		key: 'my-tool',
		title: 'My Tool',
		desc: '这里写工具说明。',
		path: '/my_tool',
		toolPath: 'my_tool',
		icon: 'pi pi-wrench'
	}
]
```

字段说明：

- `key`: 工具唯一标识
- `title`: 首页和侧边栏显示名称
- `desc`: 首页卡片描述
- `path`: 门户内路由路径
- `toolPath`: `public` 下的实际目录名
- `icon`: PrimeIcons 图标

### 3. 访问效果

配置完成后：

- 门户入口地址为 `/oss_eng_hub/`
- 点击工具后，门户路由会进入 `/oss_eng_hub/#/my_tool`
- 页面中 iframe 实际加载 `/oss_eng_hub/my_tool/index.html`

本地开发时，门户地址通常是：

- `/`
- `/#/my_tool`

注意：hash 只用于门户自身路由，工具静态页面的加载地址仍然是普通路径。

## 新项目的路由要求

门户主工程自身也已经切换为 `HashRouter`，以避免在静态托管环境下刷新门户页面时出现 404。

如果新项目本身是 React Router 或其他 SPA 路由应用，编译时请使用 `HashRouter`，不要使用 `BrowserRouter`。

原因：

- 新项目是作为静态页面被 iframe 加载
- 生产环境通常只保证 `index.html` 可访问
- 使用 `HashRouter` 可以避免刷新或直接访问内部页面时出现 404

React Router 示例：

```jsx
import { HashRouter } from 'react-router-dom'

function App() {
	return (
		<HashRouter>
			{/* routes */}
		</HashRouter>
	)
}
```

如果项目使用的是 `createHashRouter`，也保持同样原则，不要改成 `createBrowserRouter`。

## 新项目的 base URL 要求

门户主工程当前固定部署在：

```text
/oss_eng_hub/
```

因此新项目在编译时也要确认静态资源能够在这个前缀下被正确访问。

最少需要满足这两点：

- 资源请求不能假定部署在站点根目录 `/`
- 产物最终要能挂载到 `/oss_eng_hub/<toolPath>/`

当前门户主工程的 Vite 配置已经固定为：

```js
export default defineConfig({
	base: '/oss_eng_hub/'
})
```

如果你的新工具也是单独的 Vite 项目，请在构建时检查它的 `base` 配置，确保它适配 `/oss_eng_hub/` 这个部署前缀；如果资源实际发布在子目录下，也要保证最终引用路径和发布目录一致。

## 建议自检项

新增工具后，至少确认下面几项：

- 访问 `/oss_eng_hub/` 时首页能看到新工具卡片
- 门户页面刷新后不会 404
- 点击后 iframe 能正常打开 `/oss_eng_hub/<toolPath>/index.html`
- 新工具内部刷新页面不会 404
- 新工具内部静态资源不会请求到错误路径
- 如果工具有内部路由，地址栏变化应落在 hash 部分

## 目录示例

```text
public/
	my_tool/
		index.html
		assets/

src/custom/
	tools.js
```
