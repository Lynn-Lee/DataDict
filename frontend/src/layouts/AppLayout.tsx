import {
  ApartmentOutlined,
  BookOutlined,
  DatabaseOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Space, Typography } from "antd";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "@/stores/auth";

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: "/standard-library", icon: <BookOutlined />, label: <Link to="/standard-library">标准定义库</Link> },
  { key: "/tables", icon: <DatabaseOutlined />, label: <Link to="/tables">表目录</Link> },
  {
    key: "/standard-fields",
    icon: <ApartmentOutlined />,
    label: <Link to="/standard-fields">标准定义工作台</Link>,
  },
];

export default function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const selectedKey = MENU_ITEMS.find((item) => location.pathname.startsWith(item.key))?.key;

  const onLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider breakpoint="lg" collapsedWidth={0} theme="light">
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 600,
          }}
        >
          DataDict
        </div>
        <Menu
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          items={MENU_ITEMS}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: "#fff",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingInline: 24,
          }}
        >
          <Typography.Title level={4} style={{ margin: 0 }}>
            元数据知识库
          </Typography.Title>
          <Space>
            <Typography.Text type="secondary">
              {user?.real_name ?? user?.username}
            </Typography.Text>
            <Button icon={<LogoutOutlined />} onClick={onLogout}>
              退出
            </Button>
          </Space>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
