// context/AppContext.js
import React, { createContext, useState, useEffect, useCallback } from "react";
import axios from "axios";
import { message } from "antd";

export const AppContext = createContext();

export function AppProvider({ children }) {

    // =====================================================
    // 0. API 管理（全局统一）
    // =====================================================
    const API = {
        //BASE: "http://127.0.0.1:8086/app-puma",
        BASE: "https://oss-dthub.apac.bosch.com/app-puma",
        LOCAL: "http://127.0.0.1:7175",

        DOWNLOAD_CLIENT: "/download/client",

        TEMPLATE_DEPT: "/template/getUnified",
        TEMPLATE_TEAM: "/template/teamMembers",

        PROJECT_LIST: "/project/listProjects",
        PROJECT_CREATE: "/project/createProject",
        PROJECT_EDIT: "/project/editProjectMeta",
        PROJECT_DELETE: "/project/deleteProject",
        PROJECT_REORDER: "/project/reorderProjects",
        PROJECT_TAGS: "/project/getAllProjectTags",

        // ========= Todo V2 =========
        TODO_V2: {
            LIST: "/todo/list",
            CREATE: "/todo/create",
            UPDATE: "/todo/update",
            REORDER: "/todo/reorder",
            DELETE: "/todo/delete",
        },

        SSE: "/sse/stream",

        LINKS_STANDARD: "/template/standardLinks",
    };

    const request = useCallback(
        (method, url, { params = {}, data = {} } = {}) =>
            axios({
                method,
                url,
                params,
                data,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        []
    );

    // =====================================================
    // 一、全局基础状态
    // =====================================================
    const [loading, setLoading] = useState(true);
    const [user, setUser] = useState({ username: "", department: "" });
    const userId = user?.username;

    const [departments, setDepartments] = useState([]);
    const [teamMembers, setTeamMembers] = useState([]);

    // =====================================================
    // Quick Links（SearchBar 使用）
    // =====================================================
    const [links, setLinks] = useState([]);
    const loadLinks = useCallback(() => {
        return request("GET", API.BASE + API.LINKS_STANDARD)
            .then(res => {
                if (Array.isArray(res.data)) {
                    setLinks(res.data);
                } else {
                    setLinks([]);
                }
            })
            .catch(() => {
                message.warning("Load links failed");
                setLinks([]);
            });
    }, [request, API.BASE, API.LINKS_STANDARD]);

    // =====================================================
    // 二、Projects
    // =====================================================
    const [projects, setProjects] = useState([]);
    const [currentProjectId, setCurrentProjectId] = useState(null);
    const [projectRefreshFlag, setProjectRefreshFlag] = useState(0);

    // ==============================
    // Projects CRUD + Reorder
    // ==============================

    // Create Project
    const createProject = (values) => {
        if (!userId) return;
        const payload = {
            username: userId,
            projectName: values.projectName,
            department: values.department,
            owner: userId,
            editors: [userId],
            comment: values.comment || "",
            // ⭐ 正确处理 tags —— 永远不再使用 split
            tags: Array.isArray(values.tags)
                ? values.tags
                : typeof values.tags === "string"
                    ? values.tags.split(",").map(t => t.trim()).filter(Boolean)
                    : [],
                };

        return request("POST", API.BASE + API.PROJECT_CREATE, { data: payload })
            .then(() => loadProjects())
            .catch(() => message.error("Create project failed"));
    };

    // Update Project Meta
    const updateProject = (projectId, values) => {
        const payload = {
            username: userId,
            projectId,
            projectName: values.projectName,
            comment: values.comment || "",
            tags: Array.isArray(values.tags)
                ? values.tags
                : typeof values.tags === "string"
                    ? values.tags.split(",").map(t => t.trim()).filter(Boolean)
                    : [],
                };
        return request("POST", API.BASE + API.PROJECT_EDIT, { data: payload })
            .then(() => loadProjects())
            .catch(() => message.error("Update project failed"));
    };

    // Delete Project
    const deleteProject = (projectId) => {
        return request("POST", API.BASE + API.PROJECT_DELETE, {
            data: { 
                username: userId,   // ★ 必须补上
                projectId,
             }
        })
            .then(() => loadProjects())
            .catch(() => message.error("Delete project failed"));
    };

    // Reorder Projects (拖拽排序)
    const reorderProjects = (newOrder) => {
        if (!userId) return;

        // 提交给后端的 id 顺序
        const idOrder = newOrder.map((p) => p.id);

        // 前端立即更新排序
        setProjects(newOrder);

        return request("POST", API.BASE + API.PROJECT_REORDER, {
            data: {
                username: userId,
                items: idOrder,
            }
        }).catch(() => message.error("Reorder project failed"));
    };

    // AppContext.js

    const openTodoLink = (link) => {
        console.log("[openTodoLink] input link =", link, "type =", typeof link);
        
        if (!link) return;

        return request("POST", API.LOCAL + "/open/link", {
            data: { link }
        })
        .then(() => {
            message.success("Link opened");
        })
        .catch(() => {
            message.error("Open link failed");
        });
    };

    const loadProjects = useCallback((fromWS = false) => {
        if (!userId) return;

        request("GET", API.BASE + API.PROJECT_LIST, {
            params: { username: userId }
        }).then(res => {
            setProjects(res.data.projects || []);
        });
    }, [userId, request, API.BASE, API.PROJECT_LIST]);

    useEffect(() => {
        if (userId) loadProjects();
    }, [userId, loadProjects]);

    // =====================================================
    // 三、Todo V2（⭐ 核心升级点）
    // =====================================================
    const [todos, setTodos] = useState([]);

    /**
     * createTodoV2
     * 前端传完整信息（全部使用 account）
     */
    const createTodoV2 = (values) => {
        console.log("createTodoV2 values =", values);
        if (!userId) return;

        const payload = {
            title: values.title,              // ✅ V2
            due_date: values.due_date,        // ✅ 已是 YYYY-MM-DD
            comment: values.comment || "",
            tags: Array.isArray(values.tags)
            ? values.tags
            : typeof values.tags === "string"
                ? values.tags.split(",").map(t => t.trim()).filter(Boolean)
                : [],
            link: values.link || "",              // ⭐⭐ 关键修复点
            assignee_ids: values.assignee_ids?.length
            ? values.assignee_ids
            : [user.username],
            operator_id: userId,
            
        };

        return request("POST", API.BASE + API.TODO_V2.CREATE, {
            data: payload
        }).catch(() => {
            message.error("Create Todo failed");
        });
    };

    /**
     * listTodos
     * 前端只提供 operator_id
     */
    const loadTodosV2 = useCallback(() => {
        if (!userId) return;

        request("GET", API.BASE + API.TODO_V2.LIST, {
            params: { operator_id: userId }
        })
            .then(res => {
                setTodos(Array.isArray(res.data) ? res.data : []);
            })
            .catch(() => {
                setTodos([]);
            });
    }, [userId, request, API.BASE, API.TODO_V2.LIST]);

    useEffect(() => {
        if (userId) loadTodosV2();
    }, [userId, loadTodosV2]);

    /**
     * updateTodo
     * 只允许 id + operator_id + patch
     */
    const updateTodoV2 = (id, patch = {}) => {
        if (!userId) return;

        return request("POST", API.BASE + API.TODO_V2.UPDATE, {
            data: {
                id,
                operator_id: userId,
                ...patch
            }
        }).catch(() => {
            message.error("Update Todo failed");
        });
    };

    /**
     * reorderTodos
     * [{ id, order_index }]
     */
    const reorderTodosV2 = (items) => {
        if (!userId) return;

        return request("POST", API.BASE + API.TODO_V2.REORDER, {
            data: {
                operator_id: userId,
                items
            }
        }).catch(() => {
            message.error("Reorder Todos failed");
        });
    };

    /**
     * deleteTodo
     */
    const deleteTodoV2 = (id) => {
        if (!userId) return;

        return request("POST", API.BASE + API.TODO_V2.DELETE, {
            data: {
                id,
                operator_id: userId
            }
        }).catch(() => {
            message.error("Delete Todo failed");
        });
    };

    // =====================================================
    // 四、SSE（统一用 refresh，不做数据直推）
    // =====================================================
    
    useEffect(() => {
        if (!userId) return;

        const es = new EventSource(`${API.BASE}${API.SSE}?user=${userId}`);

        es.onmessage = (event) => {
            if (!event.data) return;

            try {
                const msg = JSON.parse(event.data);

                if (msg.event?.startsWith("Todo")) {
                    loadTodosV2();
                }

                if (msg.event?.startsWith("Project")) {
                    setProjectRefreshFlag(v => v + 1);
                }
            } catch {}
        };

        es.onerror = () => {
            es.close();
            setTimeout(() => {
                if (userId) loadTodosV2();
            }, 2000);
        };

        return () => es.close();
    }, [API.BASE, API.SSE, userId, loadTodosV2]);

    useEffect(() => {
        if (projectRefreshFlag) loadProjects(true);
    }, [projectRefreshFlag, loadProjects]);

    // =====================================================
    // 五、基础数据加载（User / Dept / Team）
    // =====================================================
    useEffect(() => {
        request("GET", API.LOCAL + "/userinfo")
            .then(res => {
                const d = res.data;
                setUser({ username: d.machine_id, department: d.department });
            })
            .catch(() => {
                setUser({ username: "Unknown", department: "Unknown" });
            })
            .finally(() => setLoading(false));
    }, [request, API.LOCAL]);

    useEffect(() => {
        request("GET", API.BASE + API.TEMPLATE_DEPT)
            .then(res => setDepartments(res.data.map(i => i.department)))
            .catch(() => {});
    }, [request, API.BASE, API.TEMPLATE_DEPT]);

    useEffect(() => {
    request("GET", API.BASE + API.TEMPLATE_TEAM)
        .then(res => {
        const raw = Array.isArray(res.data?.raw) ? res.data.raw : [];

        const users = raw
            .map(u => ({
            account: u.account,
            name: u.name,
            mail: u.mail,
            }))
            .sort((a, b) =>
            (a.name || "").localeCompare(b.name || "", "zh-Hans-CN", {
                sensitivity: "base",
            })
            );

        setTeamMembers(users);
        })
        .catch(() => setTeamMembers([]));
    }, [request, API.BASE, API.TEMPLATE_TEAM]);

    // =====================================================
    // 六、统计类（保持原样）
    // =====================================================
    const getProjectTagList = useCallback(async () => {
        try {
            const res = await request("GET", API.BASE + API.PROJECT_TAGS);
            const stats = res.data;

            return {
                myProjects: projects.length,
                Quotation: stats.Quotation,
                Running: stats.Running,
                SOP: stats.SOP,
                total: stats.total,
            };
        } catch {
            return {
                myProjects: 0,
                Quotation: 0,
                Running: 0,
                SOP: 0,
                total: 0,
            };
        }
    }, [projects, request, API.BASE, API.PROJECT_TAGS]);

    // =====================================================
    // Download Client
    // =====================================================
    const downloadClient = useCallback(() => {
        if (!user?.username) {
            message.warning("User not ready");
            return;
        }

        return axios({
            method: "GET",
            url: API.BASE + API.DOWNLOAD_CLIENT,
            params: {
                account: user.username,
            },
            responseType: "blob", // ⭐ 关键点
        })
            .then((res) => {
                const blob = new Blob([res.data]);
                const url = window.URL.createObjectURL(blob);

                const a = document.createElement("a");
                a.href = url;

                // 可选：后端若返回文件名
                // const disposition = res.headers["content-disposition"];
                a.download = "Client.exe";
                document.body.appendChild(a);
                a.click();
                a.remove();

                window.URL.revokeObjectURL(url);
            })
            .catch(() => {
                message.error("Download client failed");
            });
    }, [API.BASE, API.DOWNLOAD_CLIENT, user]);

    // =====================================================
    // 七、Provider
    // =====================================================
    return (
        <AppContext.Provider
            value={{
                user,
                loading,
                departments,
                teamMembers,
                projects,
                currentProjectId,
                setCurrentProjectId,
                loadProjects,
                createProject,
                updateProject,
                deleteProject,
                reorderProjects,
                todos,
                loadTodosV2,
                createTodoV2,
                updateTodoV2,
                reorderTodosV2,
                deleteTodoV2,
                getProjectTagList,
                openTodoLink,
                downloadClient,
                links,
                loadLinks,
            }}
        >
            {children}
        </AppContext.Provider>
    );
}
